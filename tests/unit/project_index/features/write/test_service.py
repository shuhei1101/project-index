from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.access import service as access_service
from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.search.types import Condition
from project_index.features.seen.store import SeenStore
from project_index.features.seen.types import LastRead, SessionKey
from project_index.features.sources.registry import SourceRegistry
from project_index.features.sources.types import (
    DirectCommitConfig,
    DocumentTable,
    ScriptEntry,
    ServedSource,
    SourceConfig,
)
from project_index.features.validation.markdown import MarkdownCheck, UncheckedKey
from project_index.features.validation.service import DocumentChecker
from project_index.features.write import service as write_service
from project_index.features.write.locks import RepositoryLocks, SourceLocks
from project_index.features.write.service import check_version, delete_docs, write_docs
from project_index.features.write.types import (
    CommitSpec,
    DeleteRequest,
    DeleteResult,
    DeleteTarget,
    Operation,
    ReferenceChange,
    TextEdit,
    WriteRequest,
    WriteResult,
)
from project_index.shared.deadline import CallLimits, Deadline
from project_index.shared.errors import (
    DeleteNotAllowedError,
    DirectCommitGeneratorError,
    DirectCommitNotPermittedError,
    DocumentReferencedError,
    InvalidArgumentError,
    ValidationFailedError,
    VersionMismatchError,
    Violation,
    WriteDeadlineExceededError,
)
from project_index.shared.hashing import content_hash, value_hash
from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.access.types import Target
    from project_index.features.documents.types import Document


def load_yaml(text: str) -> Any:
    """形の分かっている YAML の文字列を読む。"""
    return load_yaml_value(text)


DOC_1 = "id: doc-1\nname: 文書 1\n"
DOC_2 = "id: doc-2\nname: 文書 2\n"
SCHEMA = "title: rule\ntype: object\nrequired: [id, name]\n"


@dataclass
class WriteEnv:
    """書き込みに渡す部品と、作業場所・書き込み先のフォルダ。"""

    registry: SourceRegistry
    store: DocumentStore
    checker: DocumentChecker
    seen: SeenStore
    locks: SourceLocks
    source: ServedSource
    clone: Path
    worktree: Path
    repo_locks: RepositoryLocks = field(default_factory=RepositoryLocks)
    # 書き込みの作業場所。`paths_base` の配信元は、ワークツリーの中の配信元のフォルダ
    workplace: Path | None = None

    def write(
        self, now: datetime | None = None, limits: CallLimits | None = None, **request: Any
    ) -> WriteResult:
        # 期限を渡すテストだけ `limits` を渡す
        extra: dict[str, Any] = {} if limits is None else {"limits": limits}
        return write_docs(
            WriteRequest(cwd=str(self.workplace or self.worktree), **request),
            registry=self.registry,
            store=self.store,
            checker=self.checker,
            seen=self.seen,
            locks=self.locks,
            repo_locks=self.repo_locks,
            timeout_sec=10,
            now=now,
            **extra,
        )

    def delete(self, limits: CallLimits | None = None, **request: Any) -> DeleteResult:
        # 期限を渡すテストだけ `limits` を渡す
        extra: dict[str, Any] = {} if limits is None else {"limits": limits}
        return delete_docs(
            DeleteRequest(cwd=str(self.worktree), **request),
            registry=self.registry,
            store=self.store,
            checker=self.checker,
            locks=self.locks,
            repo_locks=self.repo_locks,
            timeout_sec=10,
            **extra,
        )


@pytest.fixture
def make_env(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., WriteEnv]:
    """git リポジトリとそのワークツリー x を持つ配信元と、書き込みの部品を作る関数を返す。"""

    def keep_source(source: ServedSource, _root: Path) -> ServedSource:
        # 配信元はメモリ上の設定で作るため、ワークツリーの設定の再読み込みは受け取った配信元のまま返す
        return source

    monkeypatch.setattr(access_service, "load_source_at", keep_source)

    def _make(
        files: dict[str, str] | None = None,
        *,
        tables: list[DocumentTable] | None = None,
        generators: list[ScriptEntry] | None = None,
        config_dir: str | None = None,
        **config_overrides: Any,
    ) -> WriteEnv:
        clone = git_repo(
            files
            or {
                "docs/rule/doc-1.yaml": DOC_1,
                "docs/rule/doc-2.yaml": DOC_2,
                "schemas/rule.schema.yaml": SCHEMA,
            }
        )
        worktree = clone / ".claude" / "worktrees" / "x"
        run_git(clone, "worktree", "add", "-b", "feat/x", str(worktree))
        rows = tables or [
            DocumentTable(
                id="rules",
                paths=["docs/rule/*.yaml"],
                schema_path="schemas/rule.schema.yaml",
            )
        ]
        config = make_source_config(documents=rows, generators=generators or [], **config_overrides)
        # `paths_base` の配信元: 設定のファイルと書き込める作業場所を `root` の下の `config_dir` にする
        source_folder = clone if config_dir is None else clone / config_dir
        source = make_served_source(
            id="sample",
            root=clone,
            config=config,
            is_git=True,
            repo_root=clone,
            scope_write=[str(source_folder)],
            worktree_globs=[str(clone / ".claude" / "worktrees" / "*")],
            schemas={"rules": {"type": "object", "required": ["id", "name"]}},
            config_dir=PurePosixPath(config_dir or "."),
            config_files=[source_folder / "project-index.yaml"],
        )
        store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
        return WriteEnv(
            registry=make_registry(source),
            store=store,
            checker=DocumentChecker(store, timeout_sec=10),
            seen=SeenStore(tmp_path / "seen.sqlite3", retention_days=7),
            locks=SourceLocks(),
            source=source,
            clone=clone,
            worktree=worktree,
            workplace=None if config_dir is None else worktree / config_dir,
        )

    return _make


UNINDENTED_DOC = (
    "id: doc-1\nname: 文書 1\nitems:\n- key: k1\n  label: 名称 1\n- key: k2\n  label: 名称 2\n"
)


@pytest.mark.parametrize(
    "operation",
    [
        Operation(
            op="update",
            id="doc-1",
            expected_version=content_hash(UNINDENTED_DOC),
            add_to={"items": [{"key": "k3", "label": "名称 3"}]},
        ),
        Operation(
            op="replace",
            id="doc-1",
            expected_version=content_hash(UNINDENTED_DOC),
            data={
                "id": "doc-1",
                "name": "文書 1",
                "items": [
                    {"key": "k1", "label": "名称 1"},
                    {"key": "k2", "label": "名称 2"},
                    {"key": "k3", "label": "名称 3"},
                ],
            },
        ),
    ],
    ids=["add_to", "replace"],
)
def test_write_docs_when_indent_preserved(
    make_env: Callable[..., WriteEnv], operation: Operation
) -> None:
    """元のファイルの配列の字下げを保つ（正常系）。"""
    # 準備
    env = make_env(
        {
            "docs/rule/doc-1.yaml": UNINDENTED_DOC,
            "docs/rule/doc-2.yaml": DOC_2,
            "schemas/rule.schema.yaml": SCHEMA,
        }
    )
    # 実行
    result = env.write(operations=[operation])
    # 検証
    text = (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8")
    assert text == UNINDENTED_DOC + "- key: k3\n  label: 名称 3\n"
    assert result.results[0].diff == "+ - key: k3\n+   label: 名称 3"


def test_write_docs_when_records_indent_preserved(make_env: Callable[..., WriteEnv]) -> None:
    """`records` への追加で管理用の YAML の配列の字下げを保つ（正常系）。"""
    # 準備
    notes = "items:\n- id: n1\n  path: n1.md\n"
    files = {**_notes_files(), "notes/index.yaml": notes}
    env = make_env(files, tables=[_notes_table(), _rules_table()])
    operation = Operation(
        op="create", kind="notes", data={"id": "n2", "path": "n2.md", "@body": "# n2\n"}
    )
    # 実行
    env.write(operations=[operation])
    # 検証
    text = (env.worktree / "notes/index.yaml").read_text(encoding="utf-8")
    assert text == notes + "- id: n2\n  path: n2.md\n"


def test_check_version_when_fields(make_document: Callable[..., Document]) -> None:
    """項目ごとのハッシュ（正常系）。"""
    # 準備
    document = make_document(data={"id": "doc-1", "name": "変えた名前", "description": "同じ"})
    expected = {"description": value_hash("同じ")}
    # 実行・検証
    check_version(document, expected, last_read=None)


def test_check_version_when_mismatch(make_document: Callable[..., Document]) -> None:
    """違うバージョン（異常系）。"""
    # 準備
    document = make_document(version="new123", body="id: doc-1\nname: 新しい\n")
    last_read = LastRead(
        doc_id="doc-1",
        version="old123",
        doc_kind="rules",
        content="id: doc-1\nname: 古い\n",
        read_at=datetime(2026, 10, 28, tzinfo=UTC),
    )
    # 実行・検証
    with pytest.raises(VersionMismatchError) as exc_info:
        check_version(document, "old123", last_read=last_read)
    assert exc_info.value.current == "new123"
    assert "- name: 古い" in exc_info.value.diff
    assert "+ name: 新しい" in exc_info.value.diff


def test_write_docs(make_env: Callable[..., WriteEnv], run_git: Callable[..., str]) -> None:
    """ワークツリーへの部分更新（正常系）。"""
    # 準備
    env = make_env()
    operation = Operation(
        op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"name": "新しい名前"}
    )
    # 実行
    result = env.write(operations=[operation])
    # 検証
    changed = (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8")
    assert result.applied is True
    assert result.results[0].status == "updated"
    assert changed == "id: doc-1\nname: 新しい名前\n"
    assert (env.clone / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1
    assert run_git(env.worktree, "rev-list", "--count", "HEAD").strip() == "1"


def test_write_docs_when_create(make_env: Callable[..., WriteEnv]) -> None:
    """ID を作って生成を動かす（正常系）。"""
    # 準備
    code = "import pathlib, sys; pathlib.Path('index.log').open('a').write('ran\\n')"
    generators = [ScriptEntry(id="index", run=[sys.executable, "-c", code])]
    table = DocumentTable(
        id="rules",
        paths=["docs/rule/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        after_write=["index"],
    )
    env = make_env(tables=[table], generators=generators, ids_format="{kind}-{slug}")
    operation = Operation(op="create", kind="rules", data={"name": "Doc Three"})
    # 実行
    result = env.write(operations=[operation])
    # 検証
    assert result.results[0].status == "created"
    assert result.results[0].id == "rules-doc-three"
    assert (env.worktree / "docs/rule/rules-doc-three.yaml").exists()
    assert (env.worktree / "index.log").read_text(encoding="utf-8") == "ran\n"


def test_write_docs_when_dry_run(make_env: Callable[..., WriteEnv]) -> None:
    """試しに書く（正常系）。"""
    # 準備
    env = make_env()
    operation = Operation(
        op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"name": "試し"}
    )
    # 実行
    result = env.write(operations=[operation], dry_run=True)
    # 検証
    assert result.applied is False
    assert result.results[0].diff
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1


def test_write_docs_when_partial(make_env: Callable[..., WriteEnv]) -> None:
    """一部だけ書く（正常系）。"""
    # 準備
    env = make_env()
    operations = [
        Operation(
            op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"name": "通る"}
        ),
        Operation(op="update", id="doc-2", expected_version=content_hash(DOC_2), unset=["name"]),
    ]
    # 実行
    result = env.write(operations=operations, atomic=False)
    # 検証
    assert [item.status for item in result.results] == ["updated", "failed"]
    assert result.results[1].errors
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") != DOC_1
    assert (env.worktree / "docs/rule/doc-2.yaml").read_text(encoding="utf-8") == DOC_2


def test_write_docs_when_not_git(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
    make_target: Callable[..., Target],
) -> None:
    """Git 管理外の日時（正常系）。"""
    # 準備
    root = tmp_path / "memo"
    write_files(root, {})
    table = DocumentTable(id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml")
    source = make_served_source(
        id="memo", root=root, config=make_source_config(documents=[table]), scope_write=[str(root)]
    )
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    first = datetime(2026, 10, 28, 10, 0, tzinfo=UTC)
    second = datetime(2026, 10, 28, 11, 0, tzinfo=UTC)

    def write(operation: Operation, now: datetime) -> WriteResult:
        return write_docs(
            WriteRequest(cwd=str(root), operations=[operation]),
            registry=make_registry(source),
            store=store,
            checker=DocumentChecker(store, timeout_sec=10),
            seen=SeenStore(tmp_path / "seen.sqlite3", retention_days=7),
            locks=SourceLocks(),
            repo_locks=RepositoryLocks(),
            timeout_sec=10,
            now=now,
        )

    created = write(Operation(op="create", kind="rules", data={"id": "memo-1", "name": "M"}), first)
    version = created.results[0].version
    # 実行
    write(Operation(op="update", id="memo-1", expected_version=version, set={"name": "M2"}), second)
    # 検証
    document = store.load(make_target(source)).documents[0]
    assert document.created == first
    assert document.updated == second


ITEM_1 = "id: i1\nname: I1\nrelated:\n  - to: m1\n    type: references\n"
MEMO_1 = "id: m1\nname: M1\n"


def test_write_docs_when_without_dates(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """日時を付けない種類（正常系）。"""
    # 準備
    root = tmp_path / "memo"
    write_files(root, {"items/i1.yaml": ITEM_1, "memos/m1.yaml": MEMO_1})
    items = DocumentTable(
        id="items",
        paths=["items/*.yaml"],
        schema_path="schemas/item.schema.yaml",
        write_dates=False,
    )
    memos = DocumentTable(
        id="memos", paths=["memos/*.yaml"], schema_path="schemas/memo.schema.yaml"
    )
    item_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"id": {"type": "string"}, "name": {"type": "string"}, "related": {}},
    }
    source = make_served_source(
        id="memo",
        root=root,
        config=make_source_config(documents=[items, memos]),
        scope_write=[str(root)],
        schemas={"items": item_schema, "memos": {"type": "object"}},
    )
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    now = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)

    def write(operation: Operation) -> WriteResult:
        return write_docs(
            WriteRequest(cwd=str(root), operations=[operation]),
            registry=make_registry(source),
            store=store,
            checker=DocumentChecker(store, timeout_sec=10),
            seen=SeenStore(tmp_path / "seen.sqlite3", retention_days=7),
            locks=SourceLocks(),
            repo_locks=RepositoryLocks(),
            timeout_sec=10,
            now=now,
        )

    # 実行
    created = write(Operation(op="create", kind="items", data={"id": "i2", "name": "I2"}))
    updated = write(
        Operation(op="update", id="i1", expected_version=content_hash(ITEM_1), set={"name": "I1b"})
    )
    replaced = write(
        Operation(
            op="replace",
            id="i1",
            expected_version=updated.results[0].version,
            data={"id": "i1", "name": "I1c", "related": [{"to": "m1", "type": "references"}]},
        )
    )
    renamed = write(
        Operation(op="rename", id="i1", expected_version=replaced.results[0].version, new_id="i3")
    )
    memo_renamed = write(
        Operation(op="rename", id="m1", expected_version=content_hash(MEMO_1), new_id="m2")
    )
    text_replaced = write(
        Operation(
            op="replace_text",
            filter=Condition(field="kind", op="eq", values=["items"]),
            old="I1c",
            new="I1d",
        )
    )
    # 検証
    assert [r.results[0].status for r in (created, updated, replaced)] == [
        "created",
        "updated",
        "replaced",
    ]
    assert renamed.results[0].status == "renamed"
    assert memo_renamed.results[0].status == "renamed"
    assert text_replaced.results[0].status == "updated"
    item_texts = [
        path.read_text(encoding="utf-8") for path in sorted((root / "items").glob("*.yaml"))
    ]
    assert [("created:" in text, "updated:" in text) for text in item_texts] == [
        (False, False),
        (False, False),
    ]
    assert "updated: '2026-11-18T10:00:00+00:00'" in (root / "memos/m2.yaml").read_text(
        encoding="utf-8"
    )


def test_write_docs_when_invalid(make_env: Callable[..., WriteEnv]) -> None:
    """検査に通らない（異常系）。"""
    # 準備
    env = make_env(
        {
            "docs/rule/doc-1.yaml": DOC_1,
            "docs/rule/doc-2.yaml": DOC_2,
            "schemas/rule.schema.yaml": (
                "title: rule\ntype: object\nrequired: [id, name]\n"
                "properties:\n  name:\n    type: string\n    title: 名前\n"
            ),
        }
    )
    operations = [
        Operation(
            op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"name": "通る"}
        ),
        Operation(op="update", id="doc-2", expected_version=content_hash(DOC_2), unset=["name"]),
    ]
    # 実行・検証
    with pytest.raises(ValidationFailedError) as exc_info:
        env.write(operations=operations)
    assert exc_info.value.violations[0].index == 1
    assert getattr(exc_info.value.violations[0], "schema", None) == {"title": "名前"}
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1
    assert (env.worktree / "docs/rule/doc-2.yaml").read_text(encoding="utf-8") == DOC_2


def test_write_docs_when_version_mismatch(
    make_env: Callable[..., WriteEnv], make_target: Callable[..., Target]
) -> None:
    """読んだ後に変わった（異常系）。"""
    # 準備
    env = make_env()
    target = make_target(env.source, base=env.worktree, worktree=env.worktree)
    document = env.store.get(target, ["doc-1"])[0]
    env.seen.mark_returned(SessionKey("s1"), "sample", "body", [document])
    edited = "id: doc-1\nname: 直接編集\n"
    (env.worktree / "docs/rule/doc-1.yaml").write_text(edited, encoding="utf-8")
    operation = Operation(
        op="update", id="doc-1", expected_version=document.version, set={"name": "後から"}
    )
    # 実行・検証
    with pytest.raises(VersionMismatchError) as exc_info:
        env.write(operations=[operation], session_id="s1")
    assert "+ name: 直接編集" in exc_info.value.diff
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == edited


def test_write_docs_when_too_many(make_env: Callable[..., WriteEnv]) -> None:
    """件数の上限（異常系）。"""
    # 準備
    env = make_env()
    operations = [
        Operation(op="update", id="doc-1", expected_version="x", set={"name": "n"})
        for _ in range(51)
    ]
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        env.write(operations=operations)
    assert exc_info.value.violations[0].path == "operations"


def test_write_docs_when_metadata_mapped(make_env: Callable[..., WriteEnv]) -> None:
    """共通のキー名で元の列に書く（正常系）。"""
    # 準備
    decision = "id: d1\ntitle: 決定 1\n"
    files = {
        "decisions/d1.yaml": decision,
        "schemas/decision.schema.yaml": "title: decision\ntype: object\nrequired: [id, title]\n",
    }
    table = DocumentTable(
        id="decisions",
        paths=["decisions/*.yaml"],
        schema_path="schemas/decision.schema.yaml",
        metadata={"name": "title"},
    )
    env = make_env(files, tables=[table])
    operations = [
        Operation(
            op="update",
            id="d1",
            expected_version=content_hash(decision),
            set={"name": "新しい名前"},
        ),
        Operation(op="create", kind="decisions", id="d2", data={"name": "決定 2"}),
    ]
    # 実行
    result = env.write(operations=operations)
    # 検証
    updated = (env.worktree / "decisions/d1.yaml").read_text(encoding="utf-8")
    created = (env.worktree / "decisions/d2.yaml").read_text(encoding="utf-8")
    assert [item.status for item in result.results] == ["updated", "created"]
    assert "title: 新しい名前" in updated
    assert "name:" not in updated
    assert "title: 決定 2" in created
    assert "name:" not in created


def test_write_docs_when_mdmark_warning(
    make_env: Callable[..., WriteEnv], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Markdown の値に書き方の警告がある（異常系）。"""
    # 準備
    env = make_env()

    def _fake(target: Target, document: Document, **kwargs: Any) -> MarkdownCheck:
        if document.id == "doc-2":
            violation = Violation(path="body", rule="mdmark の diagram_invalid（3 行目）", fix="A")
            return MarkdownCheck(violations=[violation], unchecked=[])
        return MarkdownCheck(violations=[], unchecked=[])

    monkeypatch.setattr(env.checker, "check_markdown", _fake)
    operations = [
        Operation(
            op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"name": "通る"}
        ),
        Operation(op="update", id="doc-2", expected_version=content_hash(DOC_2), set={"body": "x"}),
    ]
    # 実行・検証
    with pytest.raises(ValidationFailedError) as exc_info:
        env.write(operations=operations)
    assert [violation.path for violation in exc_info.value.violations] == ["operations[1].body"]
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1
    assert (env.worktree / "docs/rule/doc-2.yaml").read_text(encoding="utf-8") == DOC_2


def test_write_docs_when_mdmark_unavailable(
    make_env: Callable[..., WriteEnv], monkeypatch: pytest.MonkeyPatch
) -> None:
    """mdmark を使えない（正常系）。"""
    # 準備
    env = make_env()
    received: list[str | None] = []
    previous: list[Any] = []

    def _fake(target: Target, document: Document, **kwargs: Any) -> MarkdownCheck:
        received.append(kwargs.get("stopped"))
        previous.append(kwargs.get("previous"))
        return MarkdownCheck(
            violations=[], unchecked=[UncheckedKey(path="body", reason="R")], stopped="R"
        )

    monkeypatch.setattr(env.checker, "check_markdown", _fake)
    operations = [
        Operation(op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"body": "x"}),
        Operation(op="update", id="doc-2", expected_version=content_hash(DOC_2), set={"body": "y"}),
    ]
    # 実行
    result = env.write(operations=operations)
    # 検証
    assert result.applied is True
    assert [item.unchecked for item in result.results] == [
        [UncheckedKey(path="body", reason="R")],
        [UncheckedKey(path="body", reason="R")],
    ]
    assert received == [None, "R"]
    assert previous == [{"id": "doc-1", "name": "文書 1"}, {"id": "doc-2", "name": "文書 2"}]


NOTES = "items:\n  - id: n1\n    path: n1.md\n"
NOTE_1 = "# n1\n古い行\n"


def _notes_table() -> DocumentTable:
    """本文のファイルを持つ `records`・`body_file` の行を返す。"""
    return DocumentTable(
        id="notes",
        paths=["notes/index.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="items",
        body_file="path",
    )


def _notes_files() -> dict[str, str]:
    """本文のファイルを持つ行と、`body_file` を持たない行の文書を持つ配信元のファイルを返す。"""
    return {
        "notes/index.yaml": NOTES,
        "notes/n1.md": NOTE_1,
        "docs/rule/doc-1.yaml": DOC_1,
        "schemas/rule.schema.yaml": SCHEMA,
    }


def _rules_table() -> DocumentTable:
    """`body_file` を持たない行を返す。"""
    return DocumentTable(
        id="rules", paths=["docs/rule/*.yaml"], schema_path="schemas/rule.schema.yaml"
    )


def test_write_docs_when_body_file(make_env: Callable[..., WriteEnv]) -> None:
    """本文のファイルの作成・一部の置き換え・全体の置き換え（正常系）。"""
    # 準備
    env = make_env(_notes_files(), tables=[_notes_table(), _rules_table()])
    n1_version = value_hash([{"id": "n1", "path": "n1.md"}, NOTE_1])
    create = Operation(
        op="create", kind="notes", data={"id": "n2", "path": "n2.md", "@body": "本文\n"}
    )
    edit = Operation(
        op="update",
        id="n1",
        expected_version=n1_version,
        text_edits=[TextEdit(field="@body", old="古い行", new="新しい行")],
    )
    # 実行
    created = env.write(operations=[create])
    tried = env.write(operations=[edit], dry_run=True)
    edited = env.write(operations=[edit])
    n2_version = created.results[0].version
    replaced = env.write(
        operations=[
            Operation(
                op="update", id="n2", expected_version=n2_version, set={"@body": "置き換えた本文\n"}
            )
        ]
    )
    # 検証
    index = (env.worktree / "notes/index.yaml").read_text(encoding="utf-8")
    assert created.results[0].status == "created"
    assert "path: n2.md" in index
    assert "@body" not in index
    assert "@@ notes/n1.md" in (tried.results[0].diff or "")
    assert "新しい行" in (tried.results[0].diff or "")
    assert edited.results[0].status == "updated"
    assert edited.results[0].version == value_hash(
        [{"id": "n1", "path": "n1.md"}, "# n1\n新しい行\n"]
    )
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == "# n1\n新しい行\n"
    assert replaced.results[0].status == "updated"
    assert (env.worktree / "notes/n2.md").read_text(encoding="utf-8") == "置き換えた本文\n"


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("../../outside/n3.md", id="outside_source"),
        pytest.param("n1.md", id="existing_file"),
    ],
)
def test_write_docs_when_body_file_rejected(make_env: Callable[..., WriteEnv], path: str) -> None:
    """配信元の外・既にあるファイルを指す本文のファイル（異常系）。"""
    # 準備
    env = make_env(_notes_files(), tables=[_notes_table(), _rules_table()])
    operations = [
        Operation(op="create", kind="notes", data={"id": "n3", "path": path, "@body": "本文\n"}),
        Operation(op="create", kind="notes", data={"id": "n4", "path": "n4.md", "@body": "本文\n"}),
    ]
    # 実行・検証
    with pytest.raises(ValidationFailedError) as exc_info:
        env.write(operations=operations)
    assert [(v.index, v.path) for v in exc_info.value.violations] == [(0, "operations[0].path")]
    assert (env.worktree / "notes/index.yaml").read_text(encoding="utf-8") == NOTES
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == NOTE_1
    assert not (env.worktree / "notes/n4.md").exists()
    assert not (env.clone.parent / "outside").exists()


@pytest.mark.parametrize(
    ("operation", "expected_path", "expected_fix"),
    [
        pytest.param(
            Operation(
                op="update",
                id="doc-1",
                expected_version=content_hash(DOC_1),
                set={"@body": "x"},
            ),
            "operations[0].set.@body",
            "@body を除いてください",
            id="no_body_file",
        ),
        pytest.param(
            Operation(op="create", kind="notes", data={"id": "n2", "path": "n2.md"}),
            "operations[0].data.@body",
            "先に本文のファイルを作成",
            id="create_without_body",
        ),
        pytest.param(
            Operation(
                op="update",
                id="n1",
                expected_version=value_hash([{"id": "n1", "path": "n1.md"}, NOTE_1]),
                set={"path": "other.md"},
            ),
            "operations[0].set.path",
            "今の値",
            id="body_file_column_changed",
        ),
        pytest.param(
            Operation(
                op="update",
                id="n1",
                expected_version=value_hash([{"id": "n1", "path": "n1.md"}, NOTE_1]),
                unset=["@body"],
            ),
            "operations[0].unset",
            "unset から除いてください",
            id="unset_body",
        ),
    ],
)
def test_write_docs_when_body_not_accepted(
    make_env: Callable[..., WriteEnv], operation: Operation, expected_path: str, expected_fix: str
) -> None:
    """@body を受け付けない操作（異常系）。"""
    # 準備
    env = make_env(_notes_files(), tables=[_notes_table(), _rules_table()])
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        env.write(operations=[operation])
    assert [v.path for v in exc_info.value.violations] == [expected_path]
    assert expected_fix in exc_info.value.violations[0].fix
    assert (env.worktree / "notes/index.yaml").read_text(encoding="utf-8") == NOTES
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == NOTE_1
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1


ABSENT_NOTES = "items:\n  - id: n1\n    path: n1.md\n  - id: n3\n  - id: n5\n"


def _absent_files() -> dict[str, str]:
    """本文のファイルを持つ要素 n1 と、持たない要素 n3・n5 を持つ配信元のファイルを返す。"""
    return {
        "notes/index.yaml": ABSENT_NOTES,
        "notes/n1.md": NOTE_1,
        "schemas/rule.schema.yaml": SCHEMA,
    }


def test_write_docs_when_body_file_absent(make_env: Callable[..., WriteEnv]) -> None:
    """本文のファイルを持たない要素の作成・更新・改名・本文の付与（正常系）。"""
    # 準備
    env = make_env(_absent_files(), tables=[_notes_table()])
    # 実行
    created = env.write(operations=[Operation(op="create", kind="notes", data={"id": "n4"})])
    after_create = sorted(path.name for path in (env.worktree / "notes").iterdir())
    titled = env.write(
        operations=[
            Operation(
                op="update", id="n3", expected_version=value_hash({"id": "n3"}), set={"title": "t"}
            )
        ]
    )
    titled_index = (env.worktree / "notes/index.yaml").read_text(encoding="utf-8")
    bodied = env.write(
        operations=[
            Operation(
                op="update",
                id="n3",
                expected_version=titled.results[0].version,
                set={"path": "n3.md", "@body": "本文\n"},
            )
        ]
    )
    before_rename = sorted(path.name for path in (env.worktree / "notes").iterdir())
    renamed = env.write(
        operations=[
            Operation(op="rename", id="n5", expected_version=value_hash({"id": "n5"}), new_id="n9")
        ]
    )
    # 検証
    index = (env.worktree / "notes/index.yaml").read_text(encoding="utf-8")
    assert created.results[0].status == "created"
    assert after_create == ["index.yaml", "n1.md"]
    assert "title: t" in titled_index
    assert bodied.results[0].status == "updated"
    assert "path: n3.md" in index
    assert (env.worktree / "notes/n3.md").read_text(encoding="utf-8") == "本文\n"
    assert "@@ notes/n3.md" in (bodied.results[0].diff or "")
    assert renamed.results[0].status == "renamed"
    assert "id: n9" in index
    assert sorted(path.name for path in (env.worktree / "notes").iterdir()) == before_rename


N3_VERSION = value_hash({"id": "n3"})
N1_VERSION = value_hash([{"id": "n1", "path": "n1.md"}, NOTE_1])


@pytest.mark.parametrize(
    ("operation", "expected_path"),
    [
        pytest.param(
            Operation(op="create", kind="notes", data={"id": "n6", "@body": "x"}),
            "operations[0].data.path",
            id="create_body_only",
        ),
        pytest.param(
            Operation(op="update", id="n3", expected_version=N3_VERSION, set={"@body": "x"}),
            "operations[0].set.path",
            id="update_body_only",
        ),
        pytest.param(
            Operation(op="update", id="n3", expected_version=N3_VERSION, set={"path": "n3.md"}),
            "operations[0].set.@body",
            id="update_column_only",
        ),
        pytest.param(
            Operation(
                op="update",
                id="n3",
                expected_version=N3_VERSION,
                text_edits=[TextEdit(field="@body", old="a", new="b")],
            ),
            "operations[0].text_edits[0].field",
            id="text_edits_body",
        ),
        pytest.param(
            Operation(op="rename", id="n3", expected_version=N3_VERSION, new_path="notes/n3.md"),
            "operations[0].new_path",
            id="rename_new_path",
        ),
        pytest.param(
            Operation(op="update", id="n1", expected_version=N1_VERSION, unset=["path"]),
            "operations[0].unset.path",
            id="unset_column",
        ),
        pytest.param(
            Operation(op="replace", id="n1", expected_version=N1_VERSION, data={"id": "n1"}),
            "operations[0].data.path",
            id="replace_without_column",
        ),
    ],
)
def test_write_docs_when_body_file_absent_rejected(
    make_env: Callable[..., WriteEnv], operation: Operation, expected_path: str
) -> None:
    """本文のファイルの有無を片方だけで切り替える操作（異常系）。"""
    # 準備
    env = make_env(_absent_files(), tables=[_notes_table()])
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        env.write(operations=[operation])
    assert [v.path for v in exc_info.value.violations] == [expected_path]
    assert (env.worktree / "notes/index.yaml").read_text(encoding="utf-8") == ABSENT_NOTES
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == NOTE_1
    assert not (env.worktree / "notes/n3.md").exists()


EXISTING_BODIES = {"notes/n6.md": "# n6\n", "notes/n7.md": "# n7\n", "notes/n8.md": "# n8\n"}


def test_write_docs_when_existing_body_file_adopted(make_env: Callable[..., WriteEnv]) -> None:
    """既にあるファイルを本文のファイルにする（正常系）。"""
    # 準備
    env = make_env({**_absent_files(), **EXISTING_BODIES}, tables=[_notes_table()])
    # 実行
    created = env.write(
        operations=[Operation(op="create", kind="notes", data={"id": "n6", "path": "n6.md"})]
    )
    updated = env.write(
        operations=[
            Operation(op="update", id="n3", expected_version=N3_VERSION, set={"path": "n7.md"})
        ]
    )
    replaced = env.write(
        operations=[
            Operation(
                op="replace",
                id="n5",
                expected_version=value_hash({"id": "n5"}),
                data={"id": "n5", "path": "n8.md"},
            )
        ]
    )
    # 検証
    index = load_yaml((env.worktree / "notes/index.yaml").read_text(encoding="utf-8"))
    assert index["items"] == [
        {"id": "n1", "path": "n1.md"},
        {"id": "n3", "path": "n7.md"},
        {"id": "n5", "path": "n8.md"},
        {"id": "n6", "path": "n6.md"},
    ]
    assert created.results[0].status == "created"
    assert updated.results[0].status == "updated"
    assert replaced.results[0].status == "replaced"
    assert (env.worktree / "notes/n6.md").read_text(encoding="utf-8") == "# n6\n"
    assert (env.worktree / "notes/n7.md").read_text(encoding="utf-8") == "# n7\n"
    assert (env.worktree / "notes/n8.md").read_text(encoding="utf-8") == "# n8\n"
    assert "@@" not in (created.results[0].diff or "")
    assert "@@" not in (updated.results[0].diff or "")
    assert "@@" not in (replaced.results[0].diff or "")
    assert created.results[0].version == value_hash([{"id": "n6", "path": "n6.md"}, "# n6\n"])


@pytest.mark.parametrize(
    (
        "notes_index",
        "operations",
        "expected_index",
        "expected_rule",
        "expected_rule_kind",
        "expected_fix",
    ),
    [
        pytest.param(
            NOTES,
            [Operation(op="create", kind="notes", data={"id": "n10", "path": "n1.md"})],
            0,
            "n1",
            "n1",
            "どれでもないパス",
            id="body_file_of_other_element",
        ),
        pytest.param(
            NOTES,
            [Operation(op="create", kind="notes", data={"id": "n11", "path": "index.yaml"})],
            0,
            "notes",
            "管理用の YAML",
            "どれでもないパス",
            id="records_index",
        ),
        pytest.param(
            NOTES,
            [
                Operation(
                    op="create",
                    kind="notes",
                    data={"id": "n12", "path": "../docs/rule/doc-1.yaml"},
                )
            ],
            0,
            "doc-1",
            "doc-1",
            "どれでもないパス",
            id="file_of_document",
        ),
        pytest.param(
            NOTES,
            [
                Operation(
                    op="create", kind="notes", data={"id": "n13", "path": "n6.md", "@body": "x"}
                )
            ],
            0,
            "既にあります",
            "既にあります",
            "@body を除",
            id="body_with_existing_file",
        ),
        pytest.param(
            NOTES,
            [
                Operation(op="create", kind="notes", data={"id": "n6", "path": "n6.md"}),
                Operation(op="create", kind="notes", data={"id": "n14", "path": "n6.md"}),
            ],
            1,
            "n6",
            "n6",
            "どれでもないパス",
            id="adopted_in_same_call",
        ),
        pytest.param(
            "items: []\n",
            [Operation(op="create", kind="notes", data={"id": "n15", "path": "index.yaml"})],
            0,
            "notes",
            "管理用の YAML",
            "どれでもないパス",
            id="empty_records_index",
        ),
    ],
)
def test_write_docs_when_existing_body_file_rejected(
    make_env: Callable[..., WriteEnv],
    notes_index: str,
    operations: list[Operation],
    expected_index: int,
    expected_rule: str,
    expected_rule_kind: str,
    expected_fix: str,
) -> None:
    """既にあるファイルを本文のファイルにできない（異常系）。"""
    # 準備
    env = make_env(
        {**_notes_files(), "notes/index.yaml": notes_index, "notes/n6.md": "# n6\n"},
        tables=[_notes_table(), _rules_table()],
    )
    # 実行・検証
    with pytest.raises(ValidationFailedError) as exc_info:
        env.write(operations=operations)
    violations = exc_info.value.violations
    assert [(v.index, v.path) for v in violations] == [
        (expected_index, f"operations[{expected_index}].path")
    ]
    assert expected_rule in violations[0].rule
    assert expected_rule_kind in violations[0].rule
    assert expected_fix in violations[0].fix
    assert (env.worktree / "notes/index.yaml").read_text(encoding="utf-8") == notes_index
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == NOTE_1
    assert (env.worktree / "notes/n6.md").read_text(encoding="utf-8") == "# n6\n"
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1


GENERATE_SCRIPT = "print('generate')\n"
SKIPPED_DRAFT = "id: skip\nname: 除外\n"


def _drafts_table() -> DocumentTable:
    """`exclude[]` で `drafts/skip.yaml` を除外する行を返す。"""
    return DocumentTable(
        id="drafts",
        paths=["drafts/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        exclude=["drafts/skip.yaml"],
    )


@pytest.mark.parametrize(
    ("config_dir", "config_file", "script_file", "path", "expected_rule", "expected_file"),
    [
        pytest.param(
            None,
            "project-index.yaml",
            "scripts/generate.py",
            "../project-index.yaml",
            "配信元の設定",
            "project-index.yaml",
            id="config",
        ),
        pytest.param(
            None,
            "project-index.yaml",
            "scripts/generate.py",
            "../scripts/generate.py",
            "generators[generate]",
            "scripts/generate.py",
            id="script",
        ),
        pytest.param(
            None,
            "project-index.yaml",
            "scripts/generate.py",
            "../drafts/skip.yaml",
            "drafts",
            "drafts/skip.yaml",
            id="excluded",
        ),
        pytest.param(
            None,
            "project-index.yaml",
            "scripts/generate.py",
            "../schemas/rule.schema.yaml",
            "documents[notes].schema",
            "schemas/rule.schema.yaml",
            id="schema",
        ),
        pytest.param(
            "sub",
            "sub/project-index.yaml",
            "sub/scripts/generate.py",
            "../sub/project-index.yaml",
            "配信元の設定",
            "sub/project-index.yaml",
            id="config_under_paths_base",
        ),
        pytest.param(
            "sub",
            "sub/project-index.yaml",
            "sub/scripts/generate.py",
            "../sub/scripts/generate.py",
            "generators[generate]",
            "sub/scripts/generate.py",
            id="script_under_paths_base",
        ),
    ],
)
def test_write_docs_when_non_document_file_not_adoptable(
    make_env: Callable[..., WriteEnv],
    config_dir: str | None,
    config_file: str,
    script_file: str,
    path: str,
    expected_rule: str,
    expected_file: str,
) -> None:
    """配信元の文書でないファイルを本文のファイルにできない（異常系）。"""
    # 準備
    files = {
        **_notes_files(),
        config_file: "name: sample\n",
        script_file: GENERATE_SCRIPT,
        "drafts/skip.yaml": SKIPPED_DRAFT,
    }
    env = make_env(
        files,
        tables=[_notes_table(), _rules_table(), _drafts_table()],
        generators=[ScriptEntry(id="generate", run=["python3", "scripts/generate.py"])],
        config_dir=config_dir,
    )
    before = (env.worktree / expected_file).read_text(encoding="utf-8")
    # 実行・検証
    with pytest.raises(ValidationFailedError) as exc_info:
        env.write(
            operations=[Operation(op="create", kind="notes", data={"id": "n20", "path": path})]
        )
    violations = exc_info.value.violations
    assert [(v.index, v.path) for v in violations] == [(0, "operations[0].path")]
    assert expected_rule in violations[0].rule
    assert "どれでもないパス" in violations[0].fix
    assert (env.worktree / "notes/index.yaml").read_text(encoding="utf-8") == NOTES
    assert (env.worktree / expected_file).read_text(encoding="utf-8") == before


NESTED_NOTES = "items:\n  - id: n1\n    meta:\n      path: n1.md\n  - id: n3\n"
NESTED_N1_VERSION = value_hash([{"id": "n1", "meta": {"path": "n1.md"}}, NOTE_1])


def _nested_table() -> DocumentTable:
    """`body_file` が入れ子の列（`meta.path`）の `records` の行を返す。"""
    return DocumentTable(
        id="notes",
        paths=["notes/index.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="items",
        body_file="meta.path",
    )


def _nested_files() -> dict[str, str]:
    """入れ子の列で本文のファイルを持つ n1 と、持たない n3 を持つ配信元のファイルを返す。"""
    return {
        "notes/index.yaml": NESTED_NOTES,
        "notes/n1.md": NOTE_1,
        "schemas/rule.schema.yaml": SCHEMA,
    }


def test_write_docs_when_nested_body_file(make_env: Callable[..., WriteEnv]) -> None:
    """入れ子の `body_file` の列の置き換え・更新・本文の付与（正常系）。"""
    # 準備
    env = make_env(_nested_files(), tables=[_nested_table()])
    # 実行
    replaced = env.write(
        operations=[
            Operation(
                op="replace",
                id="n1",
                expected_version=NESTED_N1_VERSION,
                data={"id": "n1", "meta": {"path": "n1.md"}, "title": "t"},
            )
        ]
    )
    updated = env.write(
        operations=[
            Operation(
                op="update",
                id="n1",
                expected_version=replaced.results[0].version,
                set={"meta.path": "n1.md", "title": "u"},
            )
        ]
    )
    bodied = env.write(
        operations=[
            Operation(
                op="update",
                id="n3",
                expected_version=value_hash({"id": "n3"}),
                set={"meta.path": "n3.md", "@body": "本文\n"},
            )
        ]
    )
    # 検証
    index = (env.worktree / "notes/index.yaml").read_text(encoding="utf-8")
    assert replaced.results[0].status == "replaced"
    assert updated.results[0].status == "updated"
    assert "title: u" in index
    assert bodied.results[0].status == "updated"
    assert (env.worktree / "notes/n3.md").read_text(encoding="utf-8") == "本文\n"
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == NOTE_1


@pytest.mark.parametrize(
    ("operation", "expected_path"),
    [
        pytest.param(
            Operation(op="replace", id="n1", expected_version=NESTED_N1_VERSION, data={"id": "n1"}),
            "operations[0].data.meta.path",
            id="replace_without_column",
        ),
        pytest.param(
            Operation(
                op="update", id="n1", expected_version=NESTED_N1_VERSION, unset=["meta.path"]
            ),
            "operations[0].unset.meta.path",
            id="unset_column",
        ),
        pytest.param(
            Operation(
                op="update", id="n3", expected_version=value_hash({"id": "n3"}), set={"@body": "x"}
            ),
            "operations[0].set.meta.path",
            id="update_body_only",
        ),
    ],
)
def test_write_docs_when_nested_body_file_rejected(
    make_env: Callable[..., WriteEnv], operation: Operation, expected_path: str
) -> None:
    """入れ子の `body_file` の列を除く・片方だけを渡す操作（異常系）。"""
    # 準備
    env = make_env(_nested_files(), tables=[_nested_table()])
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        env.write(operations=[operation])
    assert [v.path for v in exc_info.value.violations] == [expected_path]
    assert (env.worktree / "notes/index.yaml").read_text(encoding="utf-8") == NESTED_NOTES


def _with_related() -> dict[str, str]:
    """文書 1 の `related` が文書 2 を指す配信元のファイルを返す。"""
    return {
        "docs/rule/doc-1.yaml": "id: doc-1\nname: 文書 1\nrelated:\n  - to: doc-2\n    type: references\n",
        "docs/rule/doc-2.yaml": DOC_2,
        "schemas/rule.schema.yaml": SCHEMA,
    }


def test_delete_docs(make_env: Callable[..., WriteEnv]) -> None:
    """ワークツリーから消す（正常系）。"""
    # 準備
    env = make_env()
    targets = [DeleteTarget(id="doc-2", expected_version=content_hash(DOC_2))]
    # 実行
    result = env.delete(targets=targets)
    # 検証
    assert result.results[0].status == "deleted"
    assert not (env.worktree / "docs/rule/doc-2.yaml").exists()
    assert (env.clone / "docs/rule/doc-2.yaml").exists()


def test_delete_docs_when_unlink(make_env: Callable[..., WriteEnv]) -> None:
    """参照も外す（正常系）。"""
    # 準備
    env = make_env(_with_related())
    targets = [DeleteTarget(id="doc-2", expected_version=content_hash(DOC_2))]
    # 実行
    result = env.delete(targets=targets, on_referenced="unlink")
    # 検証
    text = (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8")
    assert not (env.worktree / "docs/rule/doc-2.yaml").exists()
    assert "doc-2" not in text
    assert result.unlinked == [("doc-1", content_hash(text))]


def test_delete_docs_when_unlink_indent_preserved(make_env: Callable[..., WriteEnv]) -> None:
    """参照を外した文書の配列の字下げを保つ（正常系）。"""
    # 準備
    doc_1 = "id: doc-1\nname: 文書 1\n"
    doc_2 = (
        "id: doc-2\nname: 文書 2\nrelated:\n- to: doc-1\n  type: references\n"
        "- to: doc-3\n  type: references\n"
    )
    env = make_env(
        {
            "docs/rule/doc-1.yaml": doc_1,
            "docs/rule/doc-2.yaml": doc_2,
            "docs/rule/doc-3.yaml": "id: doc-3\nname: 文書 3\n",
            "schemas/rule.schema.yaml": SCHEMA,
        }
    )
    targets = [DeleteTarget(id="doc-1", expected_version=content_hash(doc_1))]
    # 実行
    env.delete(targets=targets, on_referenced="unlink")
    # 検証
    text = (env.worktree / "docs/rule/doc-2.yaml").read_text(encoding="utf-8")
    assert text == "id: doc-2\nname: 文書 2\nrelated:\n- to: doc-3\n  type: references\n"


def test_delete_docs_when_unlink_nested(make_env: Callable[..., WriteEnv]) -> None:
    """入れ子の参照も外す（正常系）。"""
    # 準備
    n1 = (
        "id: n1\nname: n1\nrefs:\n  - to: n2\n    type: references\n"
        "  - to: n3\n    type: references\nfunctions:\n  - name: f\n"
        "    refs:\n      - to: n2\n        type: references\n"
    )
    n2 = "id: n2\nname: n2\n"
    files = {
        "nested/n1.yaml": n1,
        "nested/n2.yaml": n2,
        "nested/n3.yaml": "id: n3\nname: n3\n",
        "schemas/rule.schema.yaml": SCHEMA,
    }
    table = DocumentTable(
        id="rules",
        paths=["nested/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"related": "**.refs[]"},
    )
    env = make_env(files, tables=[table])
    targets = [DeleteTarget(id="n2", expected_version=content_hash(n2))]
    # 実行
    result = env.delete(targets=targets, on_referenced="unlink")
    # 検証
    text = (env.worktree / "nested/n1.yaml").read_text(encoding="utf-8")
    data = load_yaml(text)
    assert not (env.worktree / "nested/n2.yaml").exists()
    assert data["refs"] == [{"to": "n3", "type": "references"}]
    assert data["functions"][0]["refs"] == []
    assert result.unlinked == [("n1", content_hash(text))]


def test_delete_docs_when_records_indent_preserved(make_env: Callable[..., WriteEnv]) -> None:
    """`records` の要素の削除で管理用の YAML の配列の字下げを保つ（正常系）。"""
    # 準備
    files = {
        "data/list.yaml": "items:\n- id: a\n  path: a.txt\n- id: b\n  path: b.txt\n",
        "data/a.txt": "a\n",
        "data/b.txt": "b\n",
    }
    table = DocumentTable(
        id="items",
        paths=["data/list.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="items",
        body_file="path",
    )
    env = make_env(files, tables=[table])
    targets = [
        DeleteTarget(id="b", expected_version=value_hash([{"id": "b", "path": "b.txt"}, "b\n"]))
    ]
    # 実行
    env.delete(targets=targets)
    # 検証
    text = (env.worktree / "data/list.yaml").read_text(encoding="utf-8")
    assert text == "items:\n- id: a\n  path: a.txt\n"


def test_delete_docs_when_records(
    make_env: Callable[..., WriteEnv],
) -> None:
    """配列の要素を消す（正常系）。"""
    # 準備
    files = {
        "data/list.yaml": "items:\n  - id: a\n    path: a.txt\n  - id: b\n    path: b.txt\n",
        "data/a.txt": "a\n",
        "data/b.txt": "b\n",
    }
    table = DocumentTable(
        id="items",
        paths=["data/list.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="items",
        body_file="path",
    )
    env = make_env(files, tables=[table])
    targets = [
        DeleteTarget(id="b", expected_version=value_hash([{"id": "b", "path": "b.txt"}, "b\n"]))
    ]
    # 実行
    env.delete(targets=targets)
    # 検証
    text = (env.worktree / "data/list.yaml").read_text(encoding="utf-8")
    assert "id: a" in text
    assert "id: b" not in text
    assert not (env.worktree / "data/b.txt").exists()
    assert (env.worktree / "data/a.txt").read_text(encoding="utf-8") == "a\n"


def test_delete_docs_when_body_file_shared(
    make_env: Callable[..., WriteEnv],
) -> None:
    """ほかの要素も指す本文のファイルを残す（正常系）。"""
    # 準備
    files = {
        "notes/index.yaml": "items:\n  - id: n1\n    path: n1.md\n  - id: n3\n    path: n1.md\n",
        "notes/n1.md": "# n1\n",
    }
    env = make_env(files, tables=[_notes_table()])
    targets = [
        DeleteTarget(
            id="n3", expected_version=value_hash([{"id": "n3", "path": "n1.md"}, "# n1\n"])
        )
    ]
    # 実行
    env.delete(targets=targets)
    # 検証
    text = (env.worktree / "notes/index.yaml").read_text(encoding="utf-8")
    assert "id: n1" in text
    assert "id: n3" not in text
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == "# n1\n"


def test_delete_docs_when_body_file_absent(make_env: Callable[..., WriteEnv]) -> None:
    """本文のファイルを持たない要素を削除する（正常系）。"""
    # 準備
    files = {
        "notes/index.yaml": "items:\n  - id: n1\n    path: n1.md\n  - id: n4\n",
        "notes/n1.md": "# n1\n",
    }
    env = make_env(files, tables=[_notes_table()])
    targets = [DeleteTarget(id="n4", expected_version=value_hash({"id": "n4"}))]
    # 実行
    env.delete(targets=targets)
    # 検証
    text = (env.worktree / "notes/index.yaml").read_text(encoding="utf-8")
    assert text == "items:\n  - id: n1\n    path: n1.md\n"
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == "# n1\n"


def test_delete_docs_when_referenced(make_env: Callable[..., WriteEnv]) -> None:
    """参照されている（異常系）。"""
    # 準備
    files = _with_related()
    env = make_env(files)
    targets = [DeleteTarget(id="doc-2", expected_version=content_hash(DOC_2))]
    # 実行・検証
    with pytest.raises(DocumentReferencedError) as exc_info:
        env.delete(targets=targets)
    assert exc_info.value.referrers == ["doc-1"]
    assert (env.worktree / "docs/rule/doc-2.yaml").read_text(encoding="utf-8") == DOC_2
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == files[
        "docs/rule/doc-1.yaml"
    ]


def test_delete_docs_when_not_allowed(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """削除を許していない（異常系）。"""
    # 準備
    root = tmp_path / "memo"
    write_files(root, {"docs/doc-1.yaml": DOC_1})
    table = DocumentTable(
        id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml", writable=False
    )
    source = make_served_source(
        id="memo", root=root, config=make_source_config(documents=[table]), scope_write=[str(root)]
    )
    store = DocumentStore(SnapshotStore(tmp_path / "snapshots"))
    request = DeleteRequest(
        cwd=str(root), targets=[DeleteTarget(id="doc-1", expected_version=content_hash(DOC_1))]
    )
    # 実行・検証
    with pytest.raises(DeleteNotAllowedError) as exc_info:
        delete_docs(
            request,
            registry=make_registry(source),
            store=store,
            checker=DocumentChecker(store, timeout_sec=10),
            locks=SourceLocks(),
            repo_locks=RepositoryLocks(),
            timeout_sec=10,
        )
    assert exc_info.value.kind == "rules"


def test_write_docs_when_tags_are_objects(make_env: Callable[..., WriteEnv]) -> None:
    """オブジェクトの配列のタグへ書き戻す（正常系）。"""
    # 準備
    rule = "id: r1\nname: 規約 1\ntags:\n  - name: a\n    main: true\n  - name: b\n"
    files = {"docs/rule/r1.yaml": rule, "schemas/rule.schema.yaml": SCHEMA}
    table = DocumentTable(
        id="rules",
        paths=["docs/rule/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"tags": "tags[].name", "main_tags": "tags[main].name"},
    )
    env = make_env(files, tables=[table])
    path = env.worktree / "docs/rule/r1.yaml"
    # 実行
    env.write(
        operations=[
            Operation(
                op="update", id="r1", expected_version=content_hash(rule), add_to={"tags": ["c"]}
            )
        ]
    )
    added = path.read_text(encoding="utf-8")
    env.write(
        operations=[
            Operation(
                op="update",
                id="r1",
                expected_version=content_hash(added),
                set={"main_tags": ["c"]},
            )
        ]
    )
    # 検証
    assert load_yaml(added)["tags"] == [
        {"name": "a", "main": True},
        {"name": "b"},
        {"name": "c"},
    ]
    assert load_yaml(path.read_text(encoding="utf-8"))["tags"] == [
        {"name": "a"},
        {"name": "b"},
        {"name": "c", "main": True},
    ]


def _limits(write_remaining: float, respond_remaining: float = 48) -> CallLimits:
    """残りの時間を決めた呼び出しの期限を作る（時計は 0 のまま進まない）。"""
    return CallLimits(
        write_deadline=Deadline(limit_sec=write_remaining, started=0, clock=lambda: 0),
        respond_by=Deadline(limit_sec=respond_remaining, started=0, clock=lambda: 0),
    )


def test_write_docs_when_deadline_passed(make_env: Callable[..., WriteEnv]) -> None:
    """置き換える前に期限を過ぎている（異常系）。"""
    # 準備
    env = make_env()
    operation = Operation(
        op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"name": "新しい名前"}
    )
    # 実行・検証
    with pytest.raises(WriteDeadlineExceededError, match="書き込みの期限"):
        env.write(operations=[operation], session_id="s1", limits=_limits(0))
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1
    assert env.seen.activity(SessionKey.of("s1", None), "sample") == []


def test_write_docs_when_deadline_passed_not_atomic(
    make_env: Callable[..., WriteEnv], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`atomic: false` でも期限の超過は全体を止める（異常系）。"""
    # 準備
    env = make_env()

    def _passed(target: Target, document: Document, **kwargs: Any) -> list[Violation]:
        raise WriteDeadlineExceededError(
            message="書き込みの期限（32 秒）を超えたため、ファイルを書き換えずに止めました（経過 33.0 秒）",
            deadline_sec=32,
            elapsed_sec=33.0,
        )

    monkeypatch.setattr(env.checker, "check", _passed)
    operations = [
        Operation(
            op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"name": "一"}
        ),
        Operation(
            op="update", id="doc-2", expected_version=content_hash(DOC_2), set={"name": "二"}
        ),
    ]
    # 実行・検証
    with pytest.raises(WriteDeadlineExceededError, match="書き込みの期限"):
        env.write(operations=operations, atomic=False, limits=_limits(30))
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1
    assert (env.worktree / "docs/rule/doc-2.yaml").read_text(encoding="utf-8") == DOC_2


def test_write_docs_when_no_time_for_generators(
    make_env: Callable[..., WriteEnv], monkeypatch: pytest.MonkeyPatch
) -> None:
    """応答の上限まで時間が無ければ生成を動かさない（正常系）。"""
    # 準備
    calls: list[Any] = []

    def counting(run: Any, **kwargs: Any) -> Any:
        calls.append(run)
        raise AssertionError

    monkeypatch.setattr(write_service, "run_script", counting)
    generators = [ScriptEntry(id="index", run=[sys.executable, "-c", "pass"])]
    table = DocumentTable(
        id="rules",
        paths=["docs/rule/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        after_write=["index"],
    )
    env = make_env(tables=[table], generators=generators, ids_format="{kind}-{slug}")
    operation = Operation(op="create", kind="rules", data={"name": "Doc Three"})
    # 実行
    result = env.write(operations=[operation], limits=_limits(30, 0))
    # 検証
    assert result.applied is True
    assert (env.worktree / "docs/rule/rules-doc-three.yaml").exists()
    assert calls == []


def test_delete_docs_when_deadline_passed(make_env: Callable[..., WriteEnv]) -> None:
    """消す前に期限を過ぎている（異常系）。"""
    # 準備
    env = make_env()
    targets = [DeleteTarget(id="doc-2", expected_version=content_hash(DOC_2))]
    # 実行・検証
    with pytest.raises(WriteDeadlineExceededError, match="書き込みの期限"):
        env.delete(targets=targets, limits=_limits(0))
    assert (env.worktree / "docs/rule/doc-2.yaml").exists()


def test_write_docs_when_rename(make_env: Callable[..., WriteEnv]) -> None:
    """改名と参照元の追随（正常系）。"""
    # 準備
    env = make_env(_with_related())
    operation = Operation(
        op="rename", id="doc-2", expected_version=content_hash(DOC_2), new_id="doc-9"
    )
    # 実行
    result = env.write(operations=[operation])
    # 検証
    renamed = result.results[0]
    referrer = result.results[1]
    assert renamed.status == "renamed"
    assert renamed.id == "doc-9"
    assert renamed.path == "docs/rule/doc-9.yaml"
    assert renamed.renamed_from == "doc-2"
    assert referrer.index == 0
    assert referrer.id == "doc-1"
    assert referrer.status == "updated"
    assert len(referrer.references) == 1
    assert not (env.worktree / "docs/rule/doc-2.yaml").exists()
    assert (env.worktree / "docs/rule/doc-9.yaml").read_text(encoding="utf-8") == (
        "id: doc-9\nname: 文書 2\n"
    )
    assert "to: doc-9" in (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        pytest.param({}, InvalidArgumentError, id="no_new_id_and_path"),
        pytest.param({"new_id": "doc-1"}, ValidationFailedError, id="id_exists"),
    ],
)
def test_write_docs_when_rename_invalid(
    make_env: Callable[..., WriteEnv], changes: dict[str, Any], error: type[Exception]
) -> None:
    """改名の引数の誤り（異常系）。"""
    # 準備
    env = make_env()
    operation = Operation(op="rename", id="doc-2", expected_version=content_hash(DOC_2), **changes)
    # 実行・検証
    with pytest.raises(error):
        env.write(operations=[operation])
    assert (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1
    assert (env.worktree / "docs/rule/doc-2.yaml").read_text(encoding="utf-8") == DOC_2


def _with_words() -> dict[str, str]:
    """タグ `topic:a` の文書 2 件と持たない文書 1 件が `旧語` を持つ配信元のファイルを返す。"""
    return {
        "docs/rule/doc-1.yaml": "id: doc-1\nname: 文書 1\ntags: [topic:a]\nbody: 旧語と旧語\n",
        "docs/rule/doc-2.yaml": "id: doc-2\nname: 旧語\ntags: [topic:a]\n",
        "docs/rule/doc-3.yaml": "id: doc-3\nname: 旧語\n",
        "schemas/rule.schema.yaml": SCHEMA,
    }


def test_write_docs_when_replace_text(make_env: Callable[..., WriteEnv]) -> None:
    """一括置換（正常系）。"""
    # 準備
    env = make_env(_with_words())
    operation = Operation(
        op="replace_text",
        filter=Condition(field="tags", op="eq", values=["topic:a"]),
        old="旧語",
        new="新語",
    )
    # 実行
    result = env.write(operations=[operation])
    # 検証
    assert [(item.index, item.id, item.status, item.count) for item in result.results] == [
        (0, "doc-1", "updated", 2),
        (0, "doc-2", "updated", 1),
    ]
    assert "body: 新語と新語" in (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8")
    assert (env.worktree / "docs/rule/doc-3.yaml").read_text(encoding="utf-8") == (
        "id: doc-3\nname: 旧語\n"
    )


def test_write_docs_when_replace_text_invalid(make_env: Callable[..., WriteEnv]) -> None:
    """置換した文書が検査に合格しない（異常系）。"""
    # 準備
    # 2 件目の文書だけが置換した `name` に改行を持ち、スキーマに合格しない
    one_line = SCHEMA + "properties:\n  name:\n    type: string\n    pattern: '^[^\\n]+$'\n"
    env = make_env({**_with_words(), "schemas/rule.schema.yaml": one_line})
    operation = Operation(
        op="replace_text",
        filter=Condition(field="tags", op="eq", values=["topic:a"]),
        old="旧語",
        new="新\n語",
    )
    # 実行
    result = env.write(operations=[operation], atomic=False)
    # 検証
    assert len(result.results) == 1
    assert result.results[0].status == "failed"
    assert "doc-2" in str(result.results[0].errors)
    assert "旧語" in (env.worktree / "docs/rule/doc-1.yaml").read_text(encoding="utf-8")
    assert "旧語" in (env.worktree / "docs/rule/doc-2.yaml").read_text(encoding="utf-8")


def test_write_docs_when_rename_body_references(make_env: Callable[..., WriteEnv]) -> None:
    """改名で本文のファイルの中のリンクも追随する（正常系）。"""
    # 準備
    files = {
        "notes/index.yaml": "items:\n  - id: n1\n    path: n1.md\n  - id: n2\n    path: n2.py\n",
        "notes/n1.md": "[文書 2](id:doc-2)\n[文書 2](../docs/rule/doc-2.yaml)\n",
        "notes/n2.py": "# id:doc-2\n",
        "docs/rule/doc-1.yaml": DOC_1,
        "docs/rule/doc-2.yaml": DOC_2,
        "schemas/rule.schema.yaml": SCHEMA,
    }
    env = make_env(files, tables=[_notes_table(), _rules_table()])
    operation = Operation(
        op="rename", id="doc-2", expected_version=content_hash(DOC_2), new_id="doc-9"
    )
    # 実行
    result = env.write(operations=[operation])
    # 検証
    n1 = [item for item in result.results if item.id == "n1"]
    assert [item.id for item in result.results if item.id == "n2"] == []
    assert n1[0].status == "updated"
    assert n1[0].references == [
        ReferenceChange(path="@body", before="id:doc-2", after="id:doc-9"),
        ReferenceChange(
            path="@body", before="../docs/rule/doc-2.yaml", after="../docs/rule/doc-9.yaml"
        ),
    ]
    assert "@@ notes/n1.md" in (n1[0].diff or "")
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == (
        "[文書 2](id:doc-9)\n[文書 2](../docs/rule/doc-9.yaml)\n"
    )
    assert (env.worktree / "notes/n2.py").read_text(encoding="utf-8") == "# id:doc-2\n"
    assert (env.worktree / "notes/index.yaml").read_text(encoding="utf-8") == files[
        "notes/index.yaml"
    ]


def _body_words() -> dict[str, str]:
    """タグ `topic:a` の要素の本文のファイルが `旧語` を持つ配信元のファイルを返す。"""
    return {
        "notes/index.yaml": (
            "items:\n"
            "  - id: n1\n    name: n1\n    path: n1.md\n    tags: [topic:a]\n"
            "  - id: n3\n    name: n3\n    path: n3.py\n    tags: [topic:a]\n"
            "  - id: n4\n    name: n4\n    path: n1.md\n    tags: [topic:a]\n"
        ),
        "notes/n1.md": "# 旧語\n旧語と別の語\n",
        "notes/n3.py": "# 旧語\n",
        "docs/rule/doc-1.yaml": DOC_1,
        "schemas/rule.schema.yaml": SCHEMA,
    }


@pytest.mark.parametrize(
    ("fields", "expected", "body"),
    [
        pytest.param(None, [(0, "n1", "updated", 2)], "# 新語\n新語と別の語\n", id="all"),
        pytest.param(["name"], [], "# 旧語\n旧語と別の語\n", id="name_only"),
        pytest.param(
            ["@body"], [(0, "n1", "updated", 2)], "# 新語\n新語と別の語\n", id="body_only"
        ),
    ],
)
def test_write_docs_when_replace_text_body(
    make_env: Callable[..., WriteEnv],
    fields: list[str] | None,
    expected: list[tuple[int, str, str, int]],
    body: str,
) -> None:
    """一括置換で本文のファイルも置換する（正常系）。"""
    # 準備
    env = make_env(_body_words(), tables=[_notes_table(), _rules_table()])
    operation = Operation(
        op="replace_text",
        filter=Condition(field="tags", op="eq", values=["topic:a"]),
        old="旧語",
        new="新語",
        fields=fields,
    )
    # 実行
    result = env.write(operations=[operation])
    # 検証
    assert [(item.index, item.id, item.status, item.count) for item in result.results] == expected
    assert (env.worktree / "notes/n1.md").read_text(encoding="utf-8") == body
    assert (env.worktree / "notes/n3.py").read_text(encoding="utf-8") == "# 旧語\n"


GITHUB_TOKEN = "gh" + "p_" + "A1b2C3d4" * 4 + "E5f6"


@dataclass
class CommitEnv:
    """直コミットの配信元と、ベアリポジトリ・data のワークツリー・呼べる作業場所。"""

    env: WriteEnv
    bare: Path
    develop: Path
    local: Path


@pytest.fixture
def make_commit_env(
    tmp_path: Path,
    run_git: Callable[..., str],
    make_env: Callable[..., WriteEnv],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
    make_registry: Callable[..., SourceRegistry],
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., CommitEnv]:
    """data へ直コミットする配信元と、ベアリポジトリへプッシュできるクローンを作る関数を返す。"""
    for name, value in {
        "GIT_AUTHOR_NAME": "tester",
        "GIT_AUTHOR_EMAIL": "tester@example.com",
        "GIT_COMMITTER_NAME": "tester",
        "GIT_COMMITTER_EMAIL": "tester@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
    }.items():
        monkeypatch.setenv(name, value)

    def _make(generators: list[ScriptEntry] | None = None) -> CommitEnv:
        env = make_env(
            {
                "docs/rule/doc-1.yaml": DOC_1,
                "docs/note/note-1.yaml": "id: note-1\nname: メモ\n",
                "docs/term/term-1.yaml": "id: term-1\nname: 用語\n",
                "schemas/rule.schema.yaml": SCHEMA,
            }
        )
        bare = tmp_path / "remote.git"
        run_git(tmp_path, "init", "--bare", "-b", "data", str(bare))
        run_git(env.clone, "remote", "add", "origin", str(bare))
        run_git(env.clone, "push", "origin", "HEAD:data")
        run_git(env.clone, "fetch", "origin")
        develop = env.clone / ".claude" / "worktrees" / "data"
        run_git(env.clone, "worktree", "add", "--track", "-b", "data", str(develop), "origin/data")
        local = tmp_path / "local"
        local.mkdir()
        after_write = ["index"] if generators else []
        tables = [
            DocumentTable(
                id="rules",
                paths=["docs/rule/*.yaml"],
                schema_path="schemas/rule.schema.yaml",
                after_write=after_write,
            ),
            DocumentTable(
                id="notes", paths=["docs/note/*.yaml"], schema_path="schemas/rule.schema.yaml"
            ),
            DocumentTable(
                id="terms", paths=["docs/term/*.yaml"], schema_path="schemas/rule.schema.yaml"
            ),
        ]
        config = make_source_config(
            documents=tables,
            generators=generators or [],
            direct_commit=DirectCommitConfig(branch="data", kinds=["rules", "terms"]),
        )
        rule_schema = {"type": "object", "required": ["id", "name"]}
        source = make_served_source(
            id="sample",
            root=env.clone,
            config=config,
            is_git=True,
            repo_root=env.clone,
            scope_write=[str(env.clone)],
            worktree_globs=[str(env.clone / ".claude" / "worktrees" / "*")],
            schemas={"rules": rule_schema, "notes": rule_schema, "terms": rule_schema},
            storage="git",
            direct_commit_scope=[str(local)],
            direct_commit_kinds={"terms": ["/other"]},
        )
        env.source = source
        env.registry = make_registry(source)
        env.worktree = local
        return CommitEnv(env=env, bare=bare, develop=develop, local=local)

    return _make


def test_write_docs_when_direct_commit_checks(
    make_commit_env: Callable[..., CommitEnv], run_git: Callable[..., str]
) -> None:
    """直コミットの確認で断る（異常系）。"""
    # 準備
    commit_env = make_commit_env()
    remote_head = run_git(commit_env.bare, "rev-parse", "data").strip()
    commit = CommitSpec(message="docs: 追加する")
    not_allowed = Operation(op="create", kind="notes", data={"id": "note-2", "name": "メモ 2"})
    secret = Operation(
        op="create", kind="rules", data={"id": "doc-9", "name": f"鍵 {GITHUB_TOKEN}"}
    )
    not_committable = Operation(op="create", kind="terms", data={"id": "term-2", "name": "用語 2"})
    # 実行・検証
    with pytest.raises(ValidationFailedError) as not_allowed_info:
        commit_env.env.write(operations=[not_allowed], source="sample", commit=commit)
    with pytest.raises(ValidationFailedError) as secret_info:
        commit_env.env.write(operations=[secret], source="sample", commit=commit)
    with pytest.raises(DirectCommitNotPermittedError, match="terms"):
        commit_env.env.write(operations=[not_committable], source="sample", commit=commit)
    assert [item.index for item in not_allowed_info.value.violations] == [0]
    assert [item.index for item in secret_info.value.violations] == [0]
    assert GITHUB_TOKEN not in repr(secret_info.value)
    assert run_git(commit_env.develop, "status", "--porcelain").strip() == ""
    assert run_git(commit_env.develop, "rev-parse", "HEAD").strip() == remote_head
    assert run_git(commit_env.bare, "rev-parse", "data").strip() == remote_head


def test_write_docs_when_direct_commit_generator_failed(
    make_commit_env: Callable[..., CommitEnv], run_git: Callable[..., str]
) -> None:
    """生成の失敗（異常系）。"""
    # 準備
    generators = [ScriptEntry(id="index", run=[sys.executable, "-c", "raise SystemExit(1)"])]
    commit_env = make_commit_env(generators=generators)
    remote_head = run_git(commit_env.bare, "rev-parse", "data").strip()
    operation = Operation(op="create", kind="rules", data={"id": "doc-9", "name": "文書 9"})
    # 実行・検証
    with pytest.raises(DirectCommitGeneratorError):
        commit_env.env.write(
            operations=[operation], source="sample", commit=CommitSpec(message="docs: 追加する")
        )
    assert not (commit_env.develop / "docs/rule/doc-9.yaml").exists()
    assert run_git(commit_env.develop, "rev-parse", "HEAD").strip() == remote_head
    assert run_git(commit_env.bare, "rev-parse", "data").strip() == remote_head


def _not_atomic(_env: CommitEnv) -> dict[str, Any]:
    """atomic: false の引数。"""
    return {"atomic": False}


def _with_worktree(env: CommitEnv) -> dict[str, Any]:
    """コミットするブランチのワークツリーを指す worktree の引数。"""
    return {"worktree": str(env.develop)}


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(_not_atomic, id="not-atomic"),
        pytest.param(_with_worktree, id="worktree"),
    ],
)
def test_write_docs_when_direct_commit_invalid_arguments(
    extra: Callable[[CommitEnv], dict[str, Any]], make_commit_env: Callable[..., CommitEnv]
) -> None:
    """引数の組み合わせ（異常系）。"""
    # 準備
    commit_env = make_commit_env()
    operation = Operation(op="create", kind="rules", data={"id": "doc-9", "name": "文書 9"})
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="commit"):
        commit_env.env.write(
            operations=[operation],
            source="sample",
            commit=CommitSpec(message="docs: 追加する"),
            **extra(commit_env),
        )


def test_write_docs_when_direct_commit_not_permitted_workplace(
    tmp_path: Path, make_commit_env: Callable[..., CommitEnv], run_git: Callable[..., str]
) -> None:
    """直コミットを呼べない作業場所は取得の前に断る（異常系）。"""
    # 準備
    commit_env = make_commit_env()
    other = tmp_path / "other"
    run_git(tmp_path, "clone", "-b", "data", str(commit_env.bare), str(other))
    (other / "ahead.txt").write_text("ahead\n", encoding="utf-8")
    run_git(other, "add", "-A")
    run_git(other, "commit", "-m", "ahead")
    run_git(other, "push", "origin", "data")
    tracking = run_git(commit_env.develop, "rev-parse", "origin/data").strip()
    head = run_git(commit_env.develop, "rev-parse", "HEAD").strip()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    commit_env.env.worktree = elsewhere
    operation = Operation(op="create", kind="rules", data={"id": "doc-9", "name": "文書 9"})
    # 実行・検証
    with pytest.raises(DirectCommitNotPermittedError, match="直コミットはできません"):
        commit_env.env.write(
            operations=[operation], source="sample", commit=CommitSpec(message="docs: 追加する")
        )
    assert run_git(commit_env.develop, "rev-parse", "origin/data").strip() == tracking
    assert run_git(commit_env.develop, "rev-parse", "HEAD").strip() == head


def test_write_docs_when_commit_branch_worktree(
    make_commit_env: Callable[..., CommitEnv], run_git: Callable[..., str]
) -> None:
    """コミットするブランチのワークツリーへの書き込みはリポジトリの排他を待つ（異常系）。"""
    # 準備
    commit_env = make_commit_env()
    env = commit_env.env
    env.worktree = commit_env.develop
    repo = Path(
        run_git(
            commit_env.develop, "rev-parse", "--path-format=absolute", "--git-common-dir"
        ).strip()
    )
    started = time.monotonic()
    limits = CallLimits(
        write_deadline=Deadline(limit_sec=0.2, started=started),
        respond_by=Deadline(limit_sec=48, started=started),
    )
    operation = Operation(
        op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"name": "待つ"}
    )
    # 実行・検証
    with env.repo_locks.hold(repo), pytest.raises(WriteDeadlineExceededError):
        env.write(operations=[operation], limits=limits)
    assert (commit_env.develop / "docs/rule/doc-1.yaml").read_text(encoding="utf-8") == DOC_1


def test_write_docs_when_other_worktree(
    make_commit_env: Callable[..., CommitEnv], run_git: Callable[..., str]
) -> None:
    """別のワークツリーへの書き込みは待たない（正常系）。"""
    # 準備
    commit_env = make_commit_env()
    env = commit_env.env
    other = env.clone / ".claude" / "worktrees" / "x"
    env.worktree = other
    repo = Path(run_git(other, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    operation = Operation(
        op="update", id="doc-1", expected_version=content_hash(DOC_1), set={"name": "待たない"}
    )
    # 実行
    with env.repo_locks.hold(repo):
        result = env.write(operations=[operation])
    # 検証
    assert result.applied is True
    assert "待たない" in (other / "docs/rule/doc-1.yaml").read_text(encoding="utf-8")


# 削除の時点の検査（`on: [delete]`）。標準入力の文書の id が「常に違反」の id なら違反を出し、
# 「消える前提」の id なら PROJECT_INDEX_DELETE_IDS にその前提の id が無いときだけ違反を出す
DELETE_GUARD = (
    "import json, os, sys\n"
    "doc = {'id': sys.stdin.read().splitlines()[0].removeprefix('id: ')}\n"
    "ids = os.environ.get('PROJECT_INDEX_DELETE_IDS', '').split()\n"
    "always, needs, needed = sys.argv[1], sys.argv[2], sys.argv[3]\n"
    "bad = doc['id'] == always or (doc['id'] == needs and needed not in ids)\n"
    "print(json.dumps([{'path': '$', 'rule': 'guard'}] if bad else []))\n"
)


def _delete_guard_tables() -> list[DocumentTable]:
    """`guard` の検査を持つ行を返す。"""
    return [
        DocumentTable(
            id="rules",
            paths=["docs/rule/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
            validators=["guard"],
        )
    ]


def _delete_guard(always: str, needs: str, needed: str) -> list[ScriptEntry]:
    """削除の時点の検査 `guard` の行を返す。"""
    run = [sys.executable, "-c", DELETE_GUARD, always, needs, needed]
    return [ScriptEntry(id="guard", run=run, on=["delete"])]


def test_delete_docs_when_delete_validator_fails(make_env: Callable[..., WriteEnv]) -> None:
    """削除の時点の検査に合格しない（異常系）。"""
    # 準備
    env = make_env(tables=_delete_guard_tables(), validators=_delete_guard("doc-2", "-", "-"))
    targets = [DeleteTarget(id="doc-2", expected_version=content_hash(DOC_2))]
    # 実行・検証
    with pytest.raises(ValidationFailedError) as caught:
        env.delete(targets=targets)
    assert [violation.index for violation in caught.value.violations] == [0]
    assert (env.worktree / "docs/rule/doc-2.yaml").exists()


def test_delete_docs_when_delete_validator_retry(make_env: Callable[..., WriteEnv]) -> None:
    """atomic: false で failed の対象を除いて検査をやり直す（正常系）。"""
    # 準備
    doc_3 = "id: doc-3\nname: 文書 3\n"
    env = make_env(
        {
            "docs/rule/doc-1.yaml": DOC_1,
            "docs/rule/doc-2.yaml": DOC_2,
            "docs/rule/doc-3.yaml": doc_3,
            "schemas/rule.schema.yaml": SCHEMA,
        },
        tables=_delete_guard_tables(),
        validators=_delete_guard("doc-1", "doc-2", "doc-1"),
    )
    targets = [
        DeleteTarget(id="doc-1", expected_version=content_hash(DOC_1)),
        DeleteTarget(id="doc-2", expected_version=content_hash(DOC_2)),
        DeleteTarget(id="doc-3", expected_version=content_hash(doc_3)),
    ]
    # 実行
    result = env.delete(targets=targets, atomic=False)
    # 検証
    assert [item.status for item in result.results] == ["failed", "failed", "deleted"]
    assert (env.worktree / "docs/rule/doc-1.yaml").exists()
    assert (env.worktree / "docs/rule/doc-2.yaml").exists()
    assert not (env.worktree / "docs/rule/doc-3.yaml").exists()

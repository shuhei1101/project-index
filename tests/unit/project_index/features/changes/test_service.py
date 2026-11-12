from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.changes.service import list_changes
from project_index.features.changes.types import (
    LAST_READ_LABEL,
    WORKTREE_LABEL,
    ChangesRequest,
    ChangesResult,
)
from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.search.types import Condition
from project_index.features.seen.store import SeenStore
from project_index.features.seen.types import SessionKey
from project_index.features.sources.registry import SourceRegistry
from project_index.features.sources.types import DocumentTable, ServedSource, SourceConfig
from project_index.shared.errors import InvalidArgumentError, LastReadNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.access.types import Target

DOC_1 = "id: doc-1\nname: 文書 1\n"
DOC_2 = "id: doc-2\nname: 文書 2\n"
DOC_1_WITH_WORD = "id: doc-1\nname: 文書 1\ndescription: 廃止予定\n"
DOC_1_REWRITTEN = "id: doc-1\nname: 文書 1\ndescription: 廃止予定です\n"
DOC_2_WITH_WORD = "id: doc-2\nname: 文書 2\ndescription: 廃止予定\n"


@dataclass
class ChangesEnv:
    """変更の一覧に渡す部品と、git リポジトリのクローン本体。"""

    registry: SourceRegistry
    store: DocumentStore
    seen: SeenStore
    source: ServedSource
    clone: Path

    def list(self, **request: Any) -> ChangesResult:
        return list_changes(
            ChangesRequest(cwd=str(self.clone), **request),
            registry=self.registry,
            store=self.store,
            seen=self.seen,
        )


@pytest.fixture
def env(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> ChangesEnv:
    """文書 1・2 を commit した git リポジトリの配信元を持つ部品を返す。"""
    clone = git_repo({"docs/doc-1.yaml": DOC_1, "docs/doc-2.yaml": DOC_2})
    table = DocumentTable(id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml")
    source = make_served_source(
        id="sample",
        root=clone,
        config=make_source_config(documents=[table]),
        is_git=True,
        repo_root=clone,
        scope_write=[str(clone)],
    )
    return ChangesEnv(
        registry=make_registry(source),
        store=DocumentStore(SnapshotStore(tmp_path / "snapshots")),
        seen=SeenStore(tmp_path / "seen.sqlite3", retention_days=7),
        source=source,
        clone=clone,
    )


@dataclass
class WordHistory:
    """語が入って消えた commit の履歴（commit は全桁）。"""

    base: str
    added: str
    rewritten: str
    removed: str


@pytest.fixture
def word_history(
    env: ChangesEnv, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> WordHistory:
    """文書 1 に語が入り、書き換えられ、消えた 3 つの commit を積む。"""
    base = run_git(env.clone, "rev-parse", "HEAD").strip()
    added = commit_all(env.clone, {"docs/doc-1.yaml": DOC_1_WITH_WORD})
    rewritten = commit_all(
        env.clone,
        {
            "docs/doc-1.yaml": DOC_1_REWRITTEN,
            "docs/doc-2.yaml": "id: doc-2\nname: 文書 2 改\n",
        },
    )
    removed = commit_all(env.clone, {"docs/doc-1.yaml": DOC_1})
    return WordHistory(base=base, added=added, rewritten=rewritten, removed=removed)


@pytest.fixture
def body_file_env(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> ChangesEnv:
    """`a.md` を指す索引 `index.yaml`（`records`・`body_file`）を持つ git リポジトリの配信元を返す。"""
    clone = git_repo({"index.yaml": "items:\n  - path: a.md\n", "a.md": "a の本文\n"})
    table = DocumentTable(
        id="src",
        paths=["index.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="items",
        body_file="path",
    )
    source = make_served_source(
        id="sample",
        root=clone,
        config=make_source_config(documents=[table]),
        is_git=True,
        repo_root=clone,
        scope_write=[str(clone)],
    )
    return ChangesEnv(
        registry=make_registry(source),
        store=DocumentStore(SnapshotStore(tmp_path / "snapshots")),
        seen=SeenStore(tmp_path / "seen.sqlite3", retention_days=7),
        source=source,
        clone=clone,
    )


@pytest.fixture
def excluded_env(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> ChangesEnv:
    """README を除外する行 `rule` と、README を集める行 `index` を持つ git リポジトリの配信元を返す。"""
    clone = git_repo({"docs/note.txt": "メモ\n"})
    # 除外が効かないと README を最初の行 `rule` が読み、種類が `rule` の文書になる
    rule = DocumentTable(
        id="rule",
        paths=["docs/rule/*.md"],
        schema_path="schemas/rule.schema.yaml",
        exclude=["README.md"],
    )
    index = DocumentTable(
        id="index", paths=["docs/**/README.md"], schema_path="schemas/rule.schema.yaml"
    )
    source = make_served_source(
        id="sample",
        root=clone,
        config=make_source_config(documents=[rule, index]),
        is_git=True,
        repo_root=clone,
        scope_write=[str(clone)],
    )
    return ChangesEnv(
        registry=make_registry(source),
        store=DocumentStore(SnapshotStore(tmp_path / "snapshots")),
        seen=SeenStore(tmp_path / "seen.sqlite3", retention_days=7),
        source=source,
        clone=clone,
    )


def test_list_changes(
    env: ChangesEnv, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> None:
    """2 つの commit の間（正常系）。"""
    # 準備
    first = run_git(env.clone, "rev-parse", "HEAD").strip()
    second = commit_all(env.clone, {"docs/doc-1.yaml": "id: doc-1\nname: 新しい名前\n"})
    # 実行
    result = env.list(**{"from": first, "to": second, "view": "full"})
    # 検証
    assert result.range_from.commit == first[:7]
    assert result.range_to.commit == second[:7]
    assert result.range_from.date is not None
    assert [(item.id, item.change, item.keys) for item in result.items] == [
        ("doc-1", "modified", ["name"])
    ]
    assert result.items[0].diff is not None
    assert "- name: 文書 1" in result.items[0].diff
    assert "+ name: 新しい名前" in result.items[0].diff
    assert result.items[0].path is None
    assert result.items[0].scope is None


def test_list_changes_when_last_read(env: ChangesEnv, make_target: Callable[..., Target]) -> None:
    """前回読んだ時点から（正常系）。"""
    # 準備
    document = env.store.get(make_target(env.source), ["doc-1"])[0]
    env.seen.mark_returned(SessionKey("s1"), "sample", "body", [document])
    (env.clone / "docs/doc-1.yaml").write_text("id: doc-1\nname: 直接編集\n", encoding="utf-8")
    # 実行
    result = env.list(session_id="s1")
    # 検証
    assert result.range_from.input == LAST_READ_LABEL
    assert [item.id for item in result.items] == ["doc-1"]
    assert result.items[0].path == str(env.clone / "docs" / "doc-1.yaml")
    assert result.items[0].scope == "summary"


def test_list_changes_when_added_and_deleted(
    env: ChangesEnv, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> None:
    """足した文書と消した文書（正常系）。"""
    # 準備
    first = run_git(env.clone, "rev-parse", "HEAD").strip()
    commit_all(
        env.clone, {"docs/doc-3.yaml": "id: doc-3\nname: 文書 3\n"}, delete=("docs/doc-2.yaml",)
    )
    # 実行
    result = env.list(**{"from": first, "view": "full"})
    # 検証
    assert [(item.id, item.change) for item in result.items] == [
        ("doc-2", "deleted"),
        ("doc-3", "added"),
    ]
    assert (result.items[0].path, result.items[0].scope) == (None, None)
    assert (result.items[1].path, result.items[1].scope) == (
        str(env.clone / "docs" / "doc-3.yaml"),
        "section",
    )


def test_list_changes_when_no_last_read(env: ChangesEnv) -> None:
    """読んだ記録が無い（異常系）。"""
    # 実行・検証
    with pytest.raises(LastReadNotFoundError):
        env.list(session_id="fresh")


def test_list_changes_when_to_without_from(env: ChangesEnv) -> None:
    """`from` の無い `to`（異常系）。"""
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        env.list(to="HEAD")
    assert exc_info.value.violations[0].path == "to"


def test_list_changes_when_excluded(
    excluded_env: ChangesEnv, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> None:
    """除外の名前に当たるファイルは次の行へ進む（正常系）。"""
    # 準備
    first = run_git(excluded_env.clone, "rev-parse", "HEAD").strip()
    commit_all(excluded_env.clone, {"docs/rule/README.md": "title: 目次\n"})
    # 実行
    result = excluded_env.list(
        **{"from": first, "filter": Condition(field="kind", op="eq", values=["index"])}
    )
    # 検証
    assert [(item.id, item.change) for item in result.items] == [("docs/rule/README.md", "added")]


def test_list_changes_when_contains(env: ChangesEnv, word_history: WordHistory) -> None:
    """語が入って消えた文書（正常系）。"""
    # 実行
    result = env.list(
        **{"from": word_history.base, "to": word_history.removed, "contains": {"value": "廃止予定"}}
    )
    without_contains = env.list(**{"from": word_history.base, "to": word_history.removed})
    # 検証
    assert [(item.id, item.change) for item in result.items] == [("doc-1", "unchanged")]
    assert result.items[0].contains_changes is not None
    assert [
        (change.kind, change.to.commit, change.count_before, change.count_after)
        for change in result.items[0].contains_changes
    ] == [
        ("added", word_history.added[:7], 0, 1),
        ("removed", word_history.removed[:7], 1, 0),
    ]
    assert [item.id for item in without_contains.items] == ["doc-2"]
    assert without_contains.items[0].contains_changes is None


def test_list_changes_when_contains_regex(env: ChangesEnv, word_history: WordHistory) -> None:
    """正規表現の語（正常系）。"""
    # 実行
    result = env.list(
        **{
            "from": word_history.base,
            "to": word_history.removed,
            "contains": {"value": "廃止.定", "regex": True},
        }
    )
    # 検証
    assert [(item.id, item.change) for item in result.items] == [("doc-1", "unchanged")]
    assert result.items[0].contains_changes is not None
    assert [
        (change.kind, change.to.commit, change.count_before, change.count_after)
        for change in result.items[0].contains_changes
    ] == [
        ("added", word_history.added[:7], 0, 1),
        ("removed", word_history.removed[:7], 1, 0),
    ]


def test_list_changes_when_contains_merge(
    env: ChangesEnv, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> None:
    """マージ commit を見ない（正常系）。"""
    # 準備
    base = run_git(env.clone, "rev-parse", "HEAD").strip()
    run_git(env.clone, "checkout", "-b", "feature")
    branch_commit = commit_all(env.clone, {"docs/doc-2.yaml": DOC_2_WITH_WORD})
    run_git(env.clone, "checkout", "develop")
    run_git(env.clone, "merge", "--no-ff", "feature", "-m", "merge")
    # 実行
    result = env.list(**{"from": base, "contains": {"value": "廃止予定"}})
    # 検証
    assert [item.id for item in result.items] == ["doc-2"]
    assert result.items[0].contains_changes is not None
    assert [(change.kind, change.to.commit) for change in result.items[0].contains_changes] == [
        ("added", branch_commit[:7])
    ]


def test_list_changes_when_contains_worktree(env: ChangesEnv, word_history: WordHistory) -> None:
    """作業ツリーの区間（正常系）。"""
    # 準備
    (env.clone / "docs/doc-1.yaml").write_text(DOC_1_WITH_WORD, encoding="utf-8")
    # 実行
    result = env.list(**{"from": word_history.base, "contains": {"value": "廃止予定"}})
    # 検証
    assert result.items[0].id == "doc-1"
    assert result.items[0].contains_changes is not None
    last = result.items[0].contains_changes[-1]
    assert last.kind == "added"
    assert last.to.input == WORKTREE_LABEL


def test_list_changes_when_contains_last_read(
    env: ChangesEnv, make_target: Callable[..., Target]
) -> None:
    """前回読んだ時点からの語（正常系）。"""
    # 準備
    document = env.store.get(make_target(env.source), ["doc-1"])[0]
    env.seen.mark_returned(SessionKey("s1"), "sample", "body", [document])
    (env.clone / "docs/doc-1.yaml").write_text(DOC_1_WITH_WORD, encoding="utf-8")
    # 実行
    result = env.list(session_id="s1", contains={"value": "廃止予定"})
    # 検証
    assert [item.id for item in result.items] == ["doc-1"]
    assert result.items[0].contains_changes is not None
    assert len(result.items[0].contains_changes) == 1
    change = result.items[0].contains_changes[0]
    assert change.kind == "added"
    assert change.from_ == result.range_from
    assert change.to == result.range_to


def test_list_changes_when_invalid_regex(env: ChangesEnv) -> None:
    """読めない正規表現（異常系）。"""
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        env.list(contains={"value": "(", "regex": True})
    assert exc_info.value.violations[0].path == "contains.value"


def test_list_changes_when_contains_body_file(
    body_file_env: ChangesEnv, commit_all: Callable[..., str], run_git: Callable[..., str]
) -> None:
    """`body_file` の文書の語（正常系）。"""
    # 準備
    base = run_git(body_file_env.clone, "rev-parse", "HEAD").strip()
    first = commit_all(body_file_env.clone, {"a.md": "a の本文\n廃止予定\n"})
    commit_all(
        body_file_env.clone,
        {
            "index.yaml": "items:\n  - path: a.md\n  - path: b.md\n",
            "b.md": "b の本文\n",
        },
    )
    third = commit_all(body_file_env.clone, {"b.md": "b の本文\n廃止予定\n"})
    # 実行
    result = body_file_env.list(**{"from": base, "to": third, "contains": {"value": "廃止予定"}})
    # 検証
    assert [item.id for item in result.items] == ["a.md", "b.md"]
    first_changes = result.items[0].contains_changes
    second_changes = result.items[1].contains_changes
    assert first_changes is not None
    assert second_changes is not None
    assert [(change.kind, change.to.commit) for change in first_changes] == [("added", first[:7])]
    assert [(change.kind, change.to.commit) for change in second_changes] == [("added", third[:7])]


def test_list_changes_when_last_read_body_file(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
    make_target: Callable[..., Target],
) -> None:
    """前回読んだ Markdown の本文の変化（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(
        root,
        {
            "notes/files.yaml": "files:\n  - path: a.md\n  - path: b.md\n",
            "notes/a.md": "a の本文\n",
            "notes/b.md": "b の本文\n",
        },
    )
    table = DocumentTable(
        id="notes",
        paths=["notes/files.yaml"],
        schema_path="schemas/rule.schema.yaml",
        records="files",
        body_file="path",
    )
    source = make_served_source(
        id="sample", root=root, config=make_source_config(documents=[table])
    )
    env = ChangesEnv(
        registry=make_registry(source),
        store=DocumentStore(SnapshotStore(tmp_path / "snapshots")),
        seen=SeenStore(tmp_path / "seen.sqlite3", retention_days=7),
        source=source,
        clone=root,
    )
    documents = env.store.get(make_target(source), ["notes/a.md", "notes/b.md"])
    env.seen.mark_returned(SessionKey("s1"), "sample", "body", documents)
    (root / "notes/a.md").write_text("a の本文を書き換えた\n", encoding="utf-8")
    # 実行
    result = env.list(session_id="s1")
    # 検証
    assert [(item.id, item.change, item.keys) for item in result.items] == [
        ("notes/a.md", "modified", ["body"])
    ]

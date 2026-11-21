from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.sources.types import (
    DocumentTable,
    ScriptEntry,
    ServedSource,
    SourceConfig,
)
from project_index.features.validation import service as service_module
from project_index.features.validation.markdown import MarkdownCheck
from project_index.features.validation.service import DocumentChecker
from project_index.integrations.scripts import ScriptResult, ScriptTimeoutError
from project_index.shared.deadline import Deadline
from project_index.shared.errors import WriteDeadlineExceededError
from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.access.types import Target
    from project_index.features.documents.types import Document


def load_yaml(text: str) -> Any:
    """形の分かっている YAML の文字列を読む。"""
    return load_yaml_value(text)


SCHEMA = {"type": "object", "required": ["name"]}

FILES_SCHEMA_TEMPLATE = Path(__file__).parents[5] / "templates" / "files.schema.yaml"


def _script(violations: list[Any], exit_code: int = 0) -> list[str]:
    """決めた違反の JSON を出して終わるコマンドを返す。"""
    code = f"import json, sys; print(json.dumps({violations!r})); sys.exit({exit_code})"
    return [sys.executable, "-c", code]


def _checker(schema: dict[str, Any]) -> DocumentChecker:
    """決めたスキーマを返す文書のストアの偽物で、文書の検査を作る。"""

    def fixed_schema(target: object, kind: str) -> dict[str, Any]:
        return schema

    store = SimpleNamespace(schema=fixed_schema, row_schema=fixed_schema)
    return DocumentChecker(store, timeout_sec=10)  # type: ignore[arg-type]


@pytest.fixture
def make_checked_target(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> Callable[..., Target]:
    """検査の行を持つ配信元の読み書きの場所を作る関数を返す。"""

    def _make(
        validators: list[ScriptEntry],
        *,
        row_validators: list[str],
        **config_overrides: Any,
    ) -> Target:
        root = tmp_path / "ws"
        root.mkdir(exist_ok=True)
        table = DocumentTable(
            id="rules",
            paths=["rules/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
            validators=row_validators,
        )
        config = make_source_config(documents=[table], validators=validators, **config_overrides)
        return make_target(make_served_source(root=root, config=config))

    return _make


def test_document_checker_check(
    make_checked_target: Callable[..., Target], make_document: Callable[..., Document]
) -> None:
    """検査の順とまとめ（正常系）。"""
    # 準備
    target = make_checked_target(
        [ScriptEntry(id="v", run=_script([{"path": "x", "rule": "bad"}]), on=["write"])],
        row_validators=["v"],
    )
    document = make_document(
        data={"id": "doc-1"},
        metadata={"id": "doc-1", "related": [{"to": "a", "type": "blocks"}]},
    )
    # 実行
    result = _checker(SCHEMA).check(target, document, on="write")
    # 検証
    assert [violation.path for violation in result] == ["$", "related[0].type", "x"]


def test_document_checker_check_when_on_read(
    make_checked_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """通す時点とキャッシュ（正常系）。"""
    # 準備
    calls: list[list[str]] = []
    real = service_module.run_script

    def counting(run: Any, **kwargs: Any) -> Any:
        calls.append(list(run))
        return real(run, **kwargs)

    monkeypatch.setattr(service_module, "run_script", counting)
    read_run = _script([])
    target = make_checked_target(
        [
            ScriptEntry(id="on-read", run=read_run, on=["read"]),
            ScriptEntry(id="on-write", run=_script([{"rule": "write only"}]), on=["write"]),
        ],
        row_validators=["on-read", "on-write"],
    )
    checker = _checker({})
    document = make_document()
    # 実行
    checker.check(target, document, on="read")
    checker.check(target, document, on="read")
    # 検証
    assert calls == [read_run]


def test_document_checker_check_when_script_fails(
    make_checked_target: Callable[..., Target], make_document: Callable[..., Document]
) -> None:
    """検査が動かない（正常系）。"""
    # 準備
    target = make_checked_target(
        [ScriptEntry(id="v", run=[sys.executable, "-c", "import sys; sys.exit(1)"], on=["write"])],
        row_validators=["v"],
    )
    # 実行
    result = _checker({}).check(target, make_document(), on="write")
    # 検証
    assert len(result) == 1
    assert "検査を実行できませんでした" in result[0].rule


def test_document_checker_check_when_new(
    make_checked_target: Callable[..., Target], make_document: Callable[..., Document]
) -> None:
    """新しい文書の ID（正常系）。"""
    # 準備
    target = make_checked_target([], row_validators=[], ids_format="{kind}-{slug}")
    document = make_document(id="X", metadata={"id": "X"})
    checker = _checker({})
    # 実行
    for_new = checker.check(target, document, on="write", new=True)
    for_existing = checker.check(target, document, on="write", new=False)
    # 検証
    assert [violation.path for violation in for_new] == ["id"]
    assert for_existing == []


def test_document_checker_check_when_records(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
) -> None:
    """records の行の要素に 1 行のスキーマを当てる（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    root.mkdir()
    table = DocumentTable(
        id="notes",
        paths=["notes/files.yaml"],
        schema_path="schemas/files.schema.yaml",
        records="files",
        body_file="path",
    )
    files_schema = load_yaml(FILES_SCHEMA_TEMPLATE.read_text(encoding="utf-8"))
    source = make_served_source(
        root=root,
        config=make_source_config(documents=[table]),
        schemas={"notes": files_schema},
    )
    document = make_document(
        id="notes/a",
        kind="notes",
        path="notes/files.yaml",
        record_index=0,
        data={"path": "a.md"},
        body="# A\n",
        body_path="notes/a.md",
        metadata={"id": "notes/a", "name": "a"},
    )
    checker = DocumentChecker(DocumentStore(SnapshotStore(tmp_path / "snapshots")), timeout_sec=10)
    # 実行
    result = checker.check(make_target(source), document, on="read")
    # 検証
    assert result == []


MARKDOWN_SCHEMA = {
    "type": "object",
    "properties": {"body": {"type": "string", "contentMediaType": "text/markdown"}},
}


def test_document_checker_check_markdown(
    make_checked_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """変えた値だけを点検に渡す（正常系）。"""
    # 準備
    target = make_checked_target([], row_validators=[])
    calls: list[tuple[dict[str, str], Path]] = []

    def _fake(values: dict[str, str], **kwargs: Any) -> MarkdownCheck:
        calls.append((dict(values), kwargs["cwd"]))
        return MarkdownCheck(violations=[], unchecked=[])

    monkeypatch.setattr(service_module, "check_markdown_values", _fake)
    document = make_document(data={"body": "b"})
    # 実行
    _checker(MARKDOWN_SCHEMA).check_markdown(target, document, previous={"body": "a"})
    # 検証
    assert calls == [({"body": "b"}, target.base)]


def test_document_checker_check_markdown_when_unchanged(
    make_checked_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Markdown の値を変えない（正常系）。"""
    # 準備
    target = make_checked_target([], row_validators=[])
    calls: list[Any] = []

    def record(*args: Any, **kwargs: Any) -> None:
        calls.append(args)

    monkeypatch.setattr(service_module, "check_markdown_values", record)
    document = make_document(data={"body": "a"})
    # 実行
    result = _checker(MARKDOWN_SCHEMA).check_markdown(target, document, previous={"body": "a"})
    # 検証
    assert result == MarkdownCheck(violations=[], unchecked=[])
    assert calls == []


class _Clock:
    """テストが進める時計。"""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_document_checker_check_when_deadline_capped(
    make_checked_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """期限までの残りの時間でスクリプトを止める（異常系）。"""
    # 準備
    clock = _Clock(0)
    received: list[float] = []

    def stopping(run: Any, **kwargs: Any) -> Any:
        received.append(kwargs["timeout_sec"])
        clock.now = 3
        raise ScriptTimeoutError(
            list(run), "制限時間（2 秒）を超えたため、スクリプトを止めました。"
        )

    monkeypatch.setattr(service_module, "run_script", stopping)
    target = make_checked_target(
        [ScriptEntry(id="v", run=_script([]), on=["write"])], row_validators=["v"]
    )
    checker = DocumentChecker(_checker({}).store, timeout_sec=30)
    deadline = Deadline(limit_sec=2, started=0, clock=clock)
    # 実行・検証
    with pytest.raises(WriteDeadlineExceededError, match="書き込みの期限"):
        checker.check(target, make_document(), on="write", deadline=deadline)
    assert received == [2]


def test_document_checker_check_when_deadline_passed(
    make_checked_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """期限を過ぎた後はスクリプトを動かさない（異常系）。"""
    # 準備
    calls: list[Any] = []

    def counting(run: Any, **kwargs: Any) -> Any:
        calls.append(run)
        raise AssertionError

    monkeypatch.setattr(service_module, "run_script", counting)
    target = make_checked_target(
        [ScriptEntry(id="v", run=_script([]), on=["write"])], row_validators=["v"]
    )
    deadline = Deadline(limit_sec=0, started=0, clock=_Clock(0))
    # 実行・検証
    with pytest.raises(WriteDeadlineExceededError, match="書き込みの期限"):
        _checker({}).check(target, make_document(), on="write", deadline=deadline)
    assert calls == []


def test_document_checker_check_when_script_timed_out(
    make_checked_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`script_timeout_sec` で止めたスクリプトは違反（正常系）。"""
    # 準備
    clock = _Clock(0)

    def stopping(run: Any, **kwargs: Any) -> Any:
        clock.now = 1
        raise ScriptTimeoutError(
            list(run), "制限時間（1 秒）を超えたため、スクリプトを止めました。"
        )

    monkeypatch.setattr(service_module, "run_script", stopping)
    target = make_checked_target(
        [ScriptEntry(id="v", run=_script([]), on=["write"])], row_validators=["v"]
    )
    checker = DocumentChecker(_checker({}).store, timeout_sec=1)
    deadline = Deadline(limit_sec=30, started=0, clock=clock)
    # 実行
    result = checker.check(target, make_document(), on="write", deadline=deadline)
    # 検証
    assert len(result) == 1
    assert (
        result[0].rule
        == "v: 検査を実行できませんでした（制限時間（1 秒）を超えたため、スクリプトを止めました。）"
    )


def _count_runs(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """スクリプトの実行を、呼ばれた `run` を記録して違反なしを返す偽物にする。"""
    calls: list[list[str]] = []

    def counting(run: Any, **kwargs: Any) -> ScriptResult:
        calls.append(list(run))
        return ScriptResult(stdout="[]", stderr="")

    monkeypatch.setattr(service_module, "run_script", counting)
    return calls


def _read_source(
    root: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    run: list[str],
    **overrides: Any,
) -> ServedSource:
    """`on: [read]` の検査 `check` を行 `rules` に持つ配信中の配信元を作る。"""
    table = DocumentTable(
        id="rules",
        paths=["rules/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        validators=["check"],
    )
    config = make_source_config(
        documents=[table], validators=[ScriptEntry(id="check", run=run, on=["read"])]
    )
    return make_served_source(root=root, config=config, **overrides)


def test_document_checker_check_when_validator_entry_changed(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """検査の行を変えると動かし直す（正常系）。"""
    # 準備
    calls = _count_runs(monkeypatch)
    root = tmp_path / "ws"
    root.mkdir()
    first = make_target(
        _read_source(root, make_source_config, make_served_source, ["python3", "a.py"])
    )
    second = make_target(
        _read_source(root, make_source_config, make_served_source, ["python3", "b.py"])
    )
    checker = _checker({})
    document = make_document()
    # 実行
    checker.check(first, document, on="read")
    checker.check(second, document, on="read")
    checker.check(first, document, on="read")
    # 検証
    assert calls == [["python3", "a.py"], ["python3", "b.py"]]


def test_document_checker_check_when_script_file_changed(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ワークツリーのスクリプトを書き換えると動かし直す（正常系）。"""
    # 準備
    calls = _count_runs(monkeypatch)
    root = tmp_path / "ws"
    script = root / "scripts" / "check.py"
    helper = root / "scripts" / "lib" / "util.py"
    helper.parent.mkdir(parents=True)
    script.write_text("a\n", encoding="utf-8")
    helper.write_text("x\n", encoding="utf-8")
    source = _read_source(
        root, make_source_config, make_served_source, ["python3", "scripts/check.py"]
    )
    target = make_target(source, worktree=root)
    checker = _checker({})
    document = make_document()
    # 実行
    checker.check(target, document, on="read")
    checker.check(target, document, on="read")
    # 書き換えは大きさを変え、更新時刻の粒度によらず状態が変わるようにする
    script.write_text("aa\n", encoding="utf-8")
    checker.check(target, document, on="read")
    helper.write_text("xx\n", encoding="utf-8")
    checker.check(target, document, on="read")
    cache = root / "scripts" / "__pycache__" / "check.cpython.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"pyc")
    checker.check(target, document, on="read")
    # 検証
    assert len(calls) == 3


def test_document_checker_check_when_worktree_and_main_clone(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ワークツリーとクローン本体のキャッシュを分ける（正常系）。"""
    # 準備
    calls = _count_runs(monkeypatch)
    root = tmp_path / "ws"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "check.py").write_text("a\n", encoding="utf-8")
    source = _read_source(
        root,
        make_source_config,
        make_served_source,
        ["python3", "scripts/check.py"],
        main_root=root,
        config_commit="a",
    )
    checker = _checker({})
    document = make_document()
    # 実行
    checker.check(make_target(source, worktree=root), document, on="read")
    checker.check(make_target(source), document, on="read")
    # 検証
    assert len(calls) == 2


def test_document_checker_check_when_config_commit_changed(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """クローン本体のスクリプトを取り出す commit が進むと動かし直す（正常系）。"""
    # 準備
    calls = _count_runs(monkeypatch)
    root = tmp_path / "ws"
    root.mkdir()
    run = ["python3", "scripts/check.py"]
    before = _read_source(
        root, make_source_config, make_served_source, run, main_root=root, config_commit="a"
    )
    after = dataclasses.replace(before, config_commit="b")
    checker = _checker({})
    document = make_document()
    # 実行
    checker.check(make_target(before), document, on="read")
    checker.check(make_target(before), document, on="read")
    checker.check(make_target(after), document, on="read")
    # 検証
    assert len(calls) == 2


def test_document_checker_check_when_script_folder_ignored(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
    run_git: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Git が無視するファイルの書き換えでは動かし直さない（正常系）。"""
    # 準備
    calls = _count_runs(monkeypatch)
    root = tmp_path / "ws"
    (root / "scripts" / "node_modules").mkdir(parents=True)
    (root / ".gitignore").write_text("scripts/node_modules/\n", encoding="utf-8")
    (root / "scripts" / "check.py").write_text("a\n", encoding="utf-8")
    ignored = root / "scripts" / "node_modules" / "a.js"
    ignored.write_text("x\n", encoding="utf-8")
    run_git(root, "init", "-b", "develop")
    run_git(root, "add", ".")
    run_git(root, "commit", "-m", "init")
    source = _read_source(
        root,
        make_source_config,
        make_served_source,
        ["python3", "scripts/check.py"],
        is_git=True,
        repo_root=root,
    )
    target = make_target(source, worktree=root)
    checker = _checker({})
    document = make_document()
    # 実行
    checker.check(target, document, on="read")
    ignored.write_text("xxx\n", encoding="utf-8")
    checker.check(target, document, on="read")
    (root / "scripts" / "new.py").write_text("b\n", encoding="utf-8")
    checker.check(target, document, on="read")
    # 検証
    assert len(calls) == 2


def test_document_checker_check_when_script_folder_has_broken_link(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """状態を取れないファイルがあってもキーを作れる（正常系）。"""
    # 準備
    calls = _count_runs(monkeypatch)
    root = tmp_path / "ws"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "check.py").write_text("a\n", encoding="utf-8")
    (root / "scripts" / "broken.py").symlink_to(root / "scripts" / "missing.py")
    source = _read_source(
        root, make_source_config, make_served_source, ["python3", "scripts/check.py"]
    )
    target = make_target(source, worktree=root)
    checker = _checker({})
    document = make_document()
    # 実行
    checker.check(target, document, on="read")
    checker.check(target, document, on="read")
    # 検証
    assert len(calls) == 1


def test_document_checker_check_when_stamps_shared(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1 回の要求の中でスクリプトの状態を使い回す（正常系）。"""
    # 準備
    _count_runs(monkeypatch)
    stamp_calls: list[Path] = []
    real = service_module.script_stamp

    def counting(base: Path, run: Any, **kwargs: Any) -> Any:
        stamp_calls.append(base)
        return real(base, run, **kwargs)

    monkeypatch.setattr(service_module, "script_stamp", counting)
    root = tmp_path / "ws"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "check.py").write_text("a\n", encoding="utf-8")
    source = _read_source(
        root, make_source_config, make_served_source, ["python3", "scripts/check.py"]
    )
    target = make_target(source, worktree=root)
    checker = _checker({})
    stamps: dict[Any, str] = {}
    # 実行
    checker.check(target, make_document(id="doc-1"), on="read", stamps=stamps)
    checker.check(target, make_document(id="doc-2", version="aaaaaa"), on="read", stamps=stamps)
    # 検証
    assert len(stamp_calls) == 1


def test_document_checker_check_when_script_outside_repository(
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
    run_git: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Git のリポジトリの外のスクリプトを指す `run` でもキーを作れる（正常系）。"""
    # 準備
    calls = _count_runs(monkeypatch)
    root = tmp_path / "ws"
    root.mkdir()
    (root / "README.md").write_text("ws\n", encoding="utf-8")
    run_git(root, "init", "-b", "develop")
    run_git(root, "add", ".")
    run_git(root, "commit", "-m", "init")
    shared = tmp_path / "shared" / "check.py"
    shared.parent.mkdir()
    shared.write_text("a\n", encoding="utf-8")
    source = _read_source(
        root,
        make_source_config,
        make_served_source,
        ["python3", "../shared/check.py"],
        is_git=True,
        repo_root=root,
    )
    target = make_target(source, worktree=root)
    checker = _checker({})
    document = make_document()
    # 実行
    checker.check(target, document, on="read")
    shared.write_text("aa\n", encoding="utf-8")
    checker.check(target, document, on="read")
    # 検証
    assert len(calls) == 2


# check_delete


def test_document_checker_check_delete(
    make_checked_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """削除の時点の検査だけを環境変数つきで実行する（正常系）。"""
    # 準備
    calls: list[tuple[list[str], Any]] = []

    def recording(run: Any, **kwargs: Any) -> ScriptResult:
        calls.append((list(run), kwargs.get("env")))
        return ScriptResult(stdout="[]", stderr="")

    monkeypatch.setattr(service_module, "run_script", recording)
    target = make_checked_target(
        [
            ScriptEntry(id="d", run=["delete-check"], on=["delete"]),
            ScriptEntry(id="w", run=["write-check"], on=["write"]),
        ],
        row_validators=["d", "w"],
    )
    # 実行
    violations = _checker({}).check_delete(target, make_document(), delete_ids=["a", "b"])
    # 検証
    assert violations == []
    assert calls == [
        (
            ["delete-check"],
            {"PROJECT_INDEX_VALIDATE_ON": "delete", "PROJECT_INDEX_DELETE_IDS": "a\nb"},
        )
    ]


def test_document_checker_check_delete_when_violation(
    make_checked_target: Callable[..., Target],
    make_document: Callable[..., Document],
) -> None:
    """検査の違反を返却する（正常系）。"""
    # 準備
    violation = {"path": "$", "rule": "参照されています", "fix": "参照元も消す"}
    target = make_checked_target(
        [ScriptEntry(id="d", run=_script([violation]), on=["delete"])], row_validators=["d"]
    )
    # 実行
    violations = _checker({}).check_delete(target, make_document(), delete_ids=["a"])
    # 検証
    assert [(v.path, v.rule) for v in violations] == [("$", "d: 参照されています")]


def test_document_checker_check_delete_when_deadline_passed(
    make_checked_target: Callable[..., Target],
    make_document: Callable[..., Document],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """期限を過ぎた後は動かさない（異常系）。"""
    # 準備
    calls: list[Any] = []

    def counting(run: Any, **kwargs: Any) -> Any:
        calls.append(run)
        raise AssertionError

    monkeypatch.setattr(service_module, "run_script", counting)
    target = make_checked_target(
        [ScriptEntry(id="d", run=_script([]), on=["delete"])], row_validators=["d"]
    )
    deadline = Deadline(limit_sec=0, started=0, clock=_Clock(0))
    # 実行・検証
    with pytest.raises(WriteDeadlineExceededError, match="書き込みの期限"):
        _checker({}).check_delete(target, make_document(), delete_ids=["a"], deadline=deadline)
    assert calls == []

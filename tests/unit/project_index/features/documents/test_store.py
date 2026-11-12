from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.documents import indexable as indexable_module
from project_index.features.documents import loader as loader_module
from project_index.features.documents import store as store_module
from project_index.features.documents.store import DocumentStore
from project_index.features.history import query as query_module
from project_index.features.history import snapshot as snapshot_module
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.sources.types import DocumentTable, ServedSource, SourceConfig
from project_index.integrations import git as git_module
from project_index.shared.errors import DocumentNotFoundError, UnknownKindError
from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.access.types import Target
    from project_index.features.documents.types import Document

OCT_01 = "2026-10-01T12:00:00+09:00"

FILES_SCHEMA_TEMPLATE = Path(__file__).parents[5] / "templates" / "files.schema.yaml"


OCT_02 = "2026-10-02T12:00:00+09:00"

RULES_TABLE = DocumentTable(
    id="rules", paths=["rules/*.yaml"], schema_path="schemas/rule.schema.yaml"
)


@pytest.fixture
def git_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """文書のストア・リビジョンの解決・書き出しが起動する git の引数を記録し、その並びを返す。"""
    calls: list[list[str]] = []
    original = git_module.run_git

    def _run(args: list[str], *rest: Any, **kwargs: Any) -> Any:
        calls.append(list(args))
        return original(args, *rest, **kwargs)

    for module in (store_module, query_module, snapshot_module):
        monkeypatch.setattr(module, "run_git", _run)
    return calls


def _git_source(
    root: Path,
    repo_root: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    *,
    source_id: str = "sample",
) -> ServedSource:
    """行 `rules` を持ち、`default_ref` が `develop` の Git の配信元を返す。"""
    return make_served_source(
        id=source_id,
        root=root,
        is_git=True,
        repo_root=repo_root,
        config=make_source_config(documents=[RULES_TABLE], default_ref="develop"),
    )


@pytest.fixture
def document_store(tmp_path: Path) -> DocumentStore:
    """リビジョンの書き出しを `tmp_path` に置く文書のストアを返す。"""
    return DocumentStore(SnapshotStore(tmp_path / "snapshots"))


@pytest.fixture
def walk_calls(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """本物の `walk_files` を包んで呼ばれた `root` を記録し、その並びを返す。"""
    calls: list[Path] = []
    original = indexable_module.walk_files

    def _walk(root: Path, **kwargs: Any) -> Any:
        calls.append(root)
        return original(root, **kwargs)

    for module in (indexable_module, loader_module, store_module):
        monkeypatch.setattr(module, "walk_files", _walk, raising=False)
    return calls


@pytest.fixture
def workspace(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> Target:
    """rules（YAML 2 件）と notes（管理用の YAML で配信する Markdown 2 件）を持つ Git の管理外の配信元の読む場所を返す。"""
    root = tmp_path / "ws"
    write_files(
        root,
        {
            "rules/a.yaml": "id: a\nname: A\n",
            "rules/b.yaml": "id: b\nname: B\n",
            "notes/files.yaml": "files:\n  - path: x.md\n  - path: y.md\n",
            "notes/x.md": "# X\n",
            "notes/y.md": "# Y\n",
        },
    )
    documents = [
        DocumentTable(id="rules", paths=["rules/*.yaml"], schema_path="schemas/rule.schema.yaml"),
        DocumentTable(
            id="notes",
            paths=["notes/files.yaml"],
            schema_path="schemas/rule.schema.yaml",
            records="files",
            body_file="path",
        ),
    ]
    source = make_served_source(root=root, config=make_source_config(documents=documents))
    return make_target(source)


def test_document_store_load(document_store: DocumentStore, workspace: Target) -> None:
    """行ごとに集める（正常系）。"""
    # 実行
    result = document_store.load(workspace)
    # 検証
    assert [(doc.kind, doc.id) for doc in result.documents] == [
        ("rules", "a"),
        ("rules", "b"),
        ("notes", "notes/x.md"),
        ("notes", "notes/y.md"),
    ]
    assert result.problems == []


def test_document_store_load_when_cached(
    document_store: DocumentStore,
    workspace: Target,
    write_files: Callable[[Path, dict[str, str]], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """変わったファイルだけ読み直す（正常系）。"""
    # 準備
    calls: list[str] = []
    real = store_module.load_file

    def recording(root: Path, path: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(path)
        return real(root, path, *args, **kwargs)

    monkeypatch.setattr(store_module, "load_file", recording)
    document_store.load(workspace)
    calls.clear()
    write_files(workspace.base, {"rules/a.yaml": "id: a\nname: A2 changed\n"})
    # 実行
    result = document_store.load(workspace)
    # 検証
    assert calls == ["rules/a.yaml"]
    assert result.documents[0].data["name"] == "A2 changed"


def test_document_store_load_when_deleted(document_store: DocumentStore, workspace: Target) -> None:
    """削除されたファイル（正常系）。"""
    # 準備
    document_store.load(workspace)
    (workspace.base / "rules" / "b.yaml").unlink()
    # 実行
    result = document_store.load(workspace)
    # 検証
    assert [doc.path for doc in result.documents if doc.kind == "rules"] == ["rules/a.yaml"]


def test_document_store_load_when_duplicate_id(
    document_store: DocumentStore,
    workspace: Target,
    write_files: Callable[[Path, dict[str, str]], None],
) -> None:
    """重なった ID（正常系）。"""
    # 準備
    write_files(
        workspace.base, {"rules/a.yaml": "id: x\nname: A\n", "rules/b.yaml": "id: x\nname: B\n"}
    )
    # 実行
    result = document_store.load(workspace, kinds=["rules"])
    # 検証
    assert [doc.path for doc in result.documents] == ["rules/a.yaml"]
    assert [(p.path, p.reason) for p in result.problems] == [("rules/b.yaml", "duplicate_id")]


def test_document_store_load_when_ref(
    tmp_path: Path,
    git_repo: Callable[..., Path],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
) -> None:
    """過去のリビジョン（正常系）。"""
    # 準備
    root = git_repo({"rules/a.yaml": "id: a\nname: old\n"}, date=OCT_01)
    first = run_git(root, "rev-parse", "HEAD").strip()
    write_files(root, {"rules/a.yaml": "id: a\nname: new\n"})
    documents = [
        DocumentTable(id="rules", paths=["rules/*.yaml"], schema_path="schemas/rule.schema.yaml")
    ]
    source = make_served_source(
        root=root,
        is_git=True,
        repo_root=root,
        config=make_source_config(documents=documents, default_ref="develop"),
    )
    target = make_target(source, ref=first)
    # 実行
    result = document_store.load(target)
    # 検証
    assert result.documents[0].data["name"] == "old"
    assert result.documents[0].updated == datetime.fromisoformat(OCT_01)


def test_document_store_load_when_commit(
    git_repo: Callable[..., Path],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解いた commit を持つ読む場所は解き直さない（正常系）。"""
    # 準備
    root = git_repo({"rules/a.yaml": "id: a\nname: old\n"}, date=OCT_01)
    first = run_git(root, "rev-parse", "HEAD").strip()
    write_files(root, {"rules/a.yaml": "id: a\nname: new\n"})
    run_git(root, "commit", "-am", "new")
    source = _git_source(root, root, make_source_config, make_served_source)
    target = make_target(source, ref="develop", commit=first)
    calls: list[str] = []
    original = query_module.resolve_ref

    def recording(repo_root: Path, ref: str, **kwargs: Any) -> Any:
        calls.append(ref)
        return original(repo_root, ref, **kwargs)

    monkeypatch.setattr(store_module, "resolve_ref", recording)
    # 実行
    result = document_store.load(target)
    # 検証
    assert result.documents[0].data["name"] == "old"
    assert calls == []


def _recording_load_file(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """本物の `load_file` を包んで呼ばれたパスを記録し、その並びを返す。"""
    calls: list[str] = []
    real = loader_module.load_file

    def recording(root: Path, path: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(path)
        return real(root, path, *args, **kwargs)

    monkeypatch.setattr(store_module, "load_file", recording)
    return calls


def _two_commits(
    git_repo: Callable[..., Path],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
) -> tuple[Path, str, str]:
    """`rules/a.yaml`・`rules/b.yaml` の commit と、`rules/a.yaml` だけを書き換えた commit を作る。"""
    root = git_repo({"rules/a.yaml": "id: a\nname: A\n", "rules/b.yaml": "id: b\nname: B\n"})
    first = run_git(root, "rev-parse", "HEAD").strip()
    write_files(root, {"rules/a.yaml": "id: a\nname: A2\n"})
    run_git(
        root, "commit", "-am", "a2", env={"GIT_AUTHOR_DATE": OCT_02, "GIT_COMMITTER_DATE": OCT_02}
    )
    second = run_git(root, "rev-parse", "HEAD").strip()
    return root, first, second


def test_document_store_load_when_revision_reused(
    git_repo: Callable[..., Path],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """新しい commit でも変わったファイルだけ読み直す（正常系）。"""
    # 準備
    root, first, second = _two_commits(git_repo, write_files, run_git)
    source = _git_source(root, root, make_source_config, make_served_source)
    calls = _recording_load_file(monkeypatch)
    document_store.load(make_target(source, ref="develop", commit=first))
    calls.clear()
    # 実行
    result = document_store.load(make_target(source, ref="develop", commit=second))
    # 検証
    assert calls == ["rules/a.yaml"]
    by_id = {document.id: document for document in result.documents}
    assert by_id["a"].data["name"] == "A2"
    assert by_id["a"].updated == datetime.fromisoformat(OCT_02)
    assert by_id["b"].data["name"] == "B"


def test_document_store_load_when_revision_reused_after_clear(
    git_repo: Callable[..., Path],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配信元の組み立て直しの後も変わったファイルだけ読み直す（正常系）。"""
    # 準備
    root, first, second = _two_commits(git_repo, write_files, run_git)
    source = _git_source(root, root, make_source_config, make_served_source)
    calls = _recording_load_file(monkeypatch)
    document_store.load(make_target(source, ref="develop", commit=first))
    document_store.clear()
    calls.clear()
    # 実行
    document_store.load(make_target(source, ref="develop", commit=second))
    # 検証
    assert calls == ["rules/a.yaml"]


def test_document_store_load_when_revision_table_changed(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """文書の行の定義が変われば読み直す（正常系）。"""
    # 準備
    root = git_repo({"rules/a.yaml": "id: a\ntitle: T\n"})
    head = run_git(root, "rev-parse", "HEAD").strip()

    def source_with(metadata: dict[str, str]) -> ServedSource:
        table = DocumentTable(
            id="rules",
            paths=["rules/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
            metadata=metadata,
        )
        return make_served_source(
            root=root,
            is_git=True,
            repo_root=root,
            config=make_source_config(documents=[table], default_ref="develop"),
        )

    calls = _recording_load_file(monkeypatch)
    document_store.load(make_target(source_with({}), ref="develop", commit=head))
    # 実行
    result = document_store.load(
        make_target(source_with({"name": "title"}), ref="develop", commit=head)
    )
    # 検証
    assert calls == ["rules/a.yaml", "rules/a.yaml"]
    assert result.documents[0].metadata["name"] == "T"


def test_document_store_load_when_dates_shared_repo(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
) -> None:
    """同じリポジトリで root の違う配信元の日時を取り違えない（正常系）。"""
    # 準備
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "develop")
    write_files(repo, {"docs/rules/a.yaml": "id: a\n"})
    run_git(repo, "add", "-A")
    run_git(
        repo, "commit", "-m", "docs", env={"GIT_AUTHOR_DATE": OCT_01, "GIT_COMMITTER_DATE": OCT_01}
    )
    write_files(repo, {"dev/rules/a.yaml": "id: a\n"})
    run_git(repo, "add", "-A")
    run_git(
        repo, "commit", "-m", "dev", env={"GIT_AUTHOR_DATE": OCT_02, "GIT_COMMITTER_DATE": OCT_02}
    )
    head = run_git(repo, "rev-parse", "HEAD").strip()
    docs = _git_source(
        repo / "docs", repo, make_source_config, make_served_source, source_id="docs"
    )
    dev = _git_source(repo / "dev", repo, make_source_config, make_served_source, source_id="dev")
    # 実行
    from_docs = document_store.load(make_target(docs, ref="develop", commit=head))
    from_dev = document_store.load(make_target(dev, ref="develop", commit=head))
    # 検証
    assert from_docs.documents[0].updated == datetime.fromisoformat(OCT_01)
    assert from_dev.documents[0].updated == datetime.fromisoformat(OCT_02)


def test_document_store_load_when_unknown_kind(
    document_store: DocumentStore, workspace: Target
) -> None:
    """無い種類（異常系）。"""
    # 実行・検証
    with pytest.raises(UnknownKindError):
        document_store.load(workspace, kinds=["x"])


def test_document_store_load_when_many_tables(
    document_store: DocumentStore,
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    walk_calls: list[Path],
) -> None:
    """行がいくつあってもフォルダを 1 回だけたどる（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(
        root,
        {
            "rules/a.yaml": "id: a\nname: A\n",
            "notes/files.yaml": "files:\n  - path: x.md\n",
            "notes/x.md": "# X\n",
            "src/files.yaml": "files:\n  - path: a.py\n",
            "src/a.py": "a = 1\n",
        },
    )
    documents = [
        DocumentTable(id="rules", paths=["rules/*.yaml"], schema_path="schemas/rule.schema.yaml"),
        DocumentTable(
            id="notes",
            paths=["notes/files.yaml"],
            schema_path="schemas/rule.schema.yaml",
            records="files",
            body_file="path",
        ),
        DocumentTable(
            id="src",
            paths=["src/files.yaml"],
            schema_path="schemas/rule.schema.yaml",
            records="files",
            body_file="path",
        ),
    ]
    source = make_served_source(root=root, config=make_source_config(documents=documents))
    # 実行
    result = document_store.load(make_target(source))
    # 検証
    assert len(walk_calls) == 1
    assert [(doc.kind, doc.id) for doc in result.documents] == [
        ("rules", "a"),
        ("notes", "notes/x.md"),
        ("src", "src/a.py"),
    ]


def test_document_store_get(document_store: DocumentStore, workspace: Target) -> None:
    """渡した順（正常系）。"""
    # 実行
    result = document_store.get(workspace, ["b", "a"])
    # 検証
    assert [doc.id for doc in result] == ["b", "a"]


def test_document_store_get_when_missing(
    document_store: DocumentStore,
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> None:
    """無い ID と近い候補（異常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(root, {"rules/auth.yaml": "id: rule-auth\nname: Auth\n"})
    documents = [
        DocumentTable(id="rules", paths=["rules/*.yaml"], schema_path="schemas/rule.schema.yaml")
    ]
    source = make_served_source(root=root, config=make_source_config(documents=documents))
    target = make_target(source)
    # 実行・検証
    with pytest.raises(DocumentNotFoundError) as exc_info:
        document_store.get(target, ["rule-auht", "zzz"])
    assert exc_info.value.missing == ["rule-auht", "zzz"]
    assert exc_info.value.candidates["rule-auht"] == ["rule-auth"]
    assert exc_info.value.candidates["zzz"] == []


def test_document_store_schema_when_worktree(
    document_store: DocumentStore,
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> None:
    """ワークツリーのスキーマ（正常系）。"""
    # 準備
    clone = tmp_path / "clone"
    worktree = tmp_path / "wt"
    write_files(clone, {"schemas/rule.schema.yaml": "type: object\nrequired: [id, name]\n"})
    write_files(worktree, {"schemas/rule.schema.yaml": "type: object\nrequired: [id]\n"})
    documents = [
        DocumentTable(
            id="rules",
            paths=["rules/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
        )
    ]
    startup = {"type": "object", "required": ["id", "name"]}
    source = make_served_source(
        root=clone,
        config=make_source_config(documents=documents),
        schemas={"rules": startup},
    )
    in_worktree = make_target(source, base=worktree, worktree=worktree)
    in_clone = make_target(source)
    # 実行
    from_worktree = document_store.schema(in_worktree, "rules")
    from_clone = document_store.schema(in_clone, "rules")
    # 検証
    assert from_worktree["required"] == ["id"]
    assert from_clone == startup


def test_document_store_schema_when_ref(
    document_store: DocumentStore,
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> None:
    """`$ref` を解いて返す（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(
        root,
        {
            "schemas/rule.schema.yaml": "type: object\n",
            "schemas/共通.schema.yaml": "$defs:\n  markdown:\n    type: string\n    title: Markdown\n",
        },
    )
    documents = [
        DocumentTable(
            id="rules",
            paths=["rules/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
        )
    ]
    raw = {"properties": {"body": {"$ref": "共通.schema.yaml#/$defs/markdown"}}}
    source = make_served_source(
        root=root, config=make_source_config(documents=documents), schemas={"rules": raw}
    )
    # 実行
    result = document_store.schema(make_target(source), "rules")
    # 検証
    assert result["properties"]["body"] == {"type": "string", "title": "Markdown"}


def test_document_store_schema_when_revision(
    git_repo: Callable[..., Path],
    write_files: Callable[[Path, dict[str, str]], None],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """リビジョンのスキーマは commit で控える（正常系）。"""
    # 準備
    root = git_repo(
        {"rules/a.yaml": "id: a\n", "schemas/rule.schema.yaml": "type: object\nrequired: [id]\n"}
    )
    first = run_git(root, "rev-parse", "HEAD").strip()
    write_files(root, {"schemas/rule.schema.yaml": "type: object\nrequired: [id, name]\n"})
    source = _git_source(root, root, make_source_config, make_served_source)
    target = make_target(source, ref="develop", commit=first)
    calls: list[str] = []
    original = document_store.snapshots.checkout

    def recording(repo_root: Path, commit: str) -> Path:
        calls.append(commit)
        return original(repo_root, commit)

    monkeypatch.setattr(document_store.snapshots, "checkout", recording)
    # 実行
    results = [document_store.schema(target, "rules"), document_store.schema(target, "rules")]
    # 検証
    assert [result["required"] for result in results] == [["id"], ["id"]]
    assert calls == [first]


def test_document_store_schema_when_revision_shared_repo(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
) -> None:
    """同じリポジトリで root の違う配信元のスキーマを取り違えない（正常系）。"""
    # 準備
    repo = git_repo(
        {
            "docs/schemas/rule.schema.yaml": "type: object\nrequired: [docs]\n",
            "dev/schemas/rule.schema.yaml": "type: object\nrequired: [dev]\n",
        }
    )
    head = run_git(repo, "rev-parse", "HEAD").strip()
    docs = _git_source(
        repo / "docs", repo, make_source_config, make_served_source, source_id="docs"
    )
    dev = _git_source(repo / "dev", repo, make_source_config, make_served_source, source_id="dev")
    # 実行
    from_docs = document_store.schema(make_target(docs, ref="develop", commit=head), "rules")
    from_dev = document_store.schema(make_target(dev, ref="develop", commit=head), "rules")
    # 検証
    assert from_docs["required"] == ["docs"]
    assert from_dev["required"] == ["dev"]


def _row_schema_source(
    root: Path,
    notes_schema: dict[str, Any],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
) -> ServedSource:
    """ファイル 1 つが 1 文書の行 rules と、管理用の YAML の行 notes を持つ配信元を返す。"""
    documents = [
        DocumentTable(id="rules", paths=["rules/*.yaml"], schema_path="schemas/rule.schema.yaml"),
        DocumentTable(
            id="notes",
            paths=["notes/files.yaml"],
            schema_path="schemas/files.schema.yaml",
            records="files",
            body_file="path",
        ),
    ]
    rule_schema = {"type": "object", "required": ["id"]}
    return make_served_source(
        root=root,
        config=make_source_config(documents=documents),
        schemas={"rules": rule_schema, "notes": notes_schema},
    )


def test_document_store_row_schema(
    document_store: DocumentStore,
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> None:
    """ファイル 1 つが 1 文書の行はそのまま（正常系）。"""
    # 準備
    source = _row_schema_source(
        tmp_path / "ws", {"type": "object"}, make_source_config, make_served_source
    )
    target = make_target(source)
    # 実行
    result = document_store.row_schema(target, "rules")
    # 検証
    assert result == document_store.schema(target, "rules")
    assert result == {"type": "object", "required": ["id"]}


def test_document_store_row_schema_when_records(
    document_store: DocumentStore,
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> None:
    """records の行は 1 行のスキーマ（正常系）。"""
    # 準備
    files_schema = load_yaml(FILES_SCHEMA_TEMPLATE.read_text(encoding="utf-8"))
    source = _row_schema_source(
        tmp_path / "ws", files_schema, make_source_config, make_served_source
    )
    # 実行
    result = document_store.row_schema(make_target(source), "notes")
    # 検証
    assert result == files_schema["properties"]["files"]["items"]
    assert result["required"] == ["path"]


def test_document_store_row_schema_when_items_missing(
    document_store: DocumentStore,
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
) -> None:
    """1 行のスキーマを取り出せない（正常系）。"""
    # 準備
    notes_schema = {
        "type": "object",
        "required": ["files"],
        "properties": {"files": {"type": "array"}},
    }
    source = _row_schema_source(
        tmp_path / "ws", notes_schema, make_source_config, make_served_source
    )
    # 実行
    result = document_store.row_schema(make_target(source), "notes")
    # 検証
    assert result == {}


def test_document_store_row_schema_when_many_documents(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
    git_calls: list[list[str]],
) -> None:
    """文書の数だけ呼んでも git を文書の数だけ起動しない（正常系）。"""
    # 準備
    files = {f"rules/r{i:02}.yaml": f"id: r{i:02}\n" for i in range(50)}
    files["schemas/rule.schema.yaml"] = "type: object\nrequired: [id]\n"
    root = git_repo(files)
    head = run_git(root, "rev-parse", "HEAD").strip()
    source = _git_source(root, root, make_source_config, make_served_source)
    target = make_target(source, ref="develop", commit=head)
    documents = document_store.load(target).documents
    git_calls.clear()
    # 実行
    results = [document_store.row_schema(target, document.kind) for document in documents]
    # 検証
    assert len(results) == 50
    assert all(result["required"] == ["id"] for result in results)
    assert git_calls == []


def test_document_store_invalidate(document_store: DocumentStore, workspace: Target) -> None:
    """同じ大きさ・同じ更新日時の書き換え（正常系）。"""
    # 準備
    target_file = workspace.base / "rules" / "a.yaml"
    document_store.load(workspace)
    stat = target_file.stat()
    target_file.write_text("id: a\nname: Z\n", encoding="utf-8")
    os.utime(target_file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    document_store.invalidate([target_file])
    # 実行
    result = document_store.load(workspace)
    # 検証
    assert result.documents[0].data["name"] == "Z"


def test_document_store_location(
    document_store: DocumentStore,
    workspace: Target,
    tmp_path: Path,
    make_document: Callable[..., Document],
) -> None:
    """作業ツリーと body_file（正常系）。"""
    # 準備
    plain = make_document(path="rules/a.yaml", body_path=None)
    code = make_document(id="src/a", path="src/files.yaml", body_path="src/a.py")
    # 実行
    plain_location = document_store.location(workspace, plain)
    code_location = document_store.location(workspace, code)
    # 検証
    assert plain_location == str(tmp_path / "ws" / "rules" / "a.yaml")
    assert code_location == str(tmp_path / "ws" / "src" / "a.py")


def test_document_store_location_when_worktree(
    document_store: DocumentStore,
    workspace: Target,
    tmp_path: Path,
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
) -> None:
    """ワークツリー（正常系）。"""
    # 準備
    worktree = tmp_path / "ws" / ".claude" / "worktrees" / "x"
    target = make_target(workspace.source, base=worktree, worktree=worktree)
    document = make_document(path="rules/a.yaml", body_path=None)
    # 実行
    result = document_store.location(target, document)
    # 検証
    assert result == str(worktree / "rules" / "a.yaml")


def test_document_store_location_when_ref(
    document_store: DocumentStore,
    workspace: Target,
    make_target: Callable[..., Target],
    make_document: Callable[..., Document],
) -> None:
    """リビジョン（正常系）。"""
    # 準備
    target = make_target(workspace.source, ref="HEAD")
    document = make_document(path="rules/a.yaml", body_path=None)
    # 実行
    result = document_store.location(target, document)
    # 検証
    assert result is None


def _sync_source(
    root: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
) -> ServedSource:
    """`metadata` の列の欠けを数える行 rules と、管理用の YAML の行 src を持つ配信元を返す。"""
    documents = [
        DocumentTable(
            id="rules",
            paths=["rules/*.yaml"],
            schema_path="schemas/rule.schema.yaml",
            metadata={"name": "title"},
        ),
        DocumentTable(
            id="src",
            paths=["src/files.yaml"],
            schema_path="schemas/rule.schema.yaml",
            records="files",
            body_file="path",
        ),
    ]
    return make_served_source(root=root, config=make_source_config(documents=documents))


def test_check_sync(
    document_store: DocumentStore,
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
) -> None:
    """3 種のずれ（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(
        root,
        {
            "rules/a.yaml": "id: a\ntitle: A\n",
            "rules/b.yaml": "id: b\n",
            "src/files.yaml": "files:\n  - path: a.py\n  - path: c.py\n",
            "src/a.py": "a = 1\n",
            "src/d.py": "d = 4\n",
        },
    )
    source = _sync_source(root, make_source_config, make_served_source)
    # 実行
    report = store_module.check_sync(document_store, source)
    # 検証
    assert report.source_id == "sample"
    assert report.missing_refs == ["rules: b: name（title）"]
    assert report.unindexed_files == ["src: src/d.py"]
    assert len(report.missing_body_files) == 1
    assert report.missing_body_files[0].startswith("src/files.yaml: ")
    assert "c.py" in report.missing_body_files[0]


def test_check_sync_when_clean(
    document_store: DocumentStore,
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
) -> None:
    """ずれが無い（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(
        root,
        {
            "rules/a.yaml": "id: a\ntitle: A\n",
            "rules/b.yaml": "id: b\ntitle: B\n",
            "src/files.yaml": "files:\n  - path: a.py\n  - path: d.py\n",
            "src/a.py": "a = 1\n",
            "src/d.py": "d = 4\n",
        },
    )
    source = _sync_source(root, make_source_config, make_served_source)
    # 実行
    report = store_module.check_sync(document_store, source)
    # 検証
    assert report.missing_refs == []
    assert report.unindexed_files == []
    assert report.missing_body_files == []
    assert report.unresolved_related == []


def test_check_sync_when_related_unresolved(
    document_store: DocumentStore,
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
) -> None:
    """どの文書にも当たらない関連（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(
        root,
        {
            "src/files.yaml": (
                "files:\n"
                "  - path: a.py\n"
                "    related:\n"
                "      - to: src/b.py\n"
                "      - to: src/z.py\n"
                "      - to: other-doc\n"
                "        source: other\n"
                "  - path: b.py\n"
            ),
            "src/a.py": "a = 1\n",
            "src/b.py": "b = 2\n",
        },
    )
    source = _sync_source(root, make_source_config, make_served_source)
    # 実行
    report = store_module.check_sync(document_store, source)
    # 検証
    assert report.unresolved_related == ["src: src/a.py: src/z.py"]


def test_check_sync_when_alias_violation(
    document_store: DocumentStore,
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
) -> None:
    """エイリアスのキーの違反（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(
        root,
        {
            "terms/broken.yaml": "id: broken\nname: 壊れた用語\ndescription: 型の違う別名\naliases: 3\n"
        },
    )
    documents = [
        DocumentTable(
            id="terms",
            paths=["terms/*.yaml"],
            schema_path="schemas/term.schema.yaml",
            alias_type="term",
        )
    ]
    source = make_served_source(root=root, config=make_source_config(documents=documents))
    # 実行
    report = store_module.check_sync(document_store, source)
    # 検証
    assert [(item.doc, item.path) for item in report.alias_violations] == [
        ("terms/broken.yaml", "aliases")
    ]


def test_check_sync_when_walked_once(
    document_store: DocumentStore,
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    walk_calls: list[Path],
) -> None:
    """配信元のフォルダを 1 回だけたどる（正常系）。"""
    # 準備
    root = tmp_path / "ws"
    write_files(
        root,
        {
            "rules/a.yaml": "id: a\ntitle: A\n",
            "rules/b.yaml": "id: b\n",
            "src/files.yaml": "files:\n  - path: a.py\n  - path: c.py\n",
            "src/a.py": "a = 1\n",
            "src/d.py": "d = 4\n",
        },
    )
    source = _sync_source(root, make_source_config, make_served_source)
    # 実行
    report = store_module.check_sync(document_store, source)
    # 検証
    assert len(walk_calls) == 1
    assert report.missing_refs == ["rules: b: name（title）"]
    assert report.unindexed_files == ["src: src/d.py"]
    assert len(report.missing_body_files) == 1
    assert report.missing_body_files[0].startswith("src/files.yaml: ")
    assert "c.py" in report.missing_body_files[0]


def test_store_schema_when_paths_base_set(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    tmp_path: Path,
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_target: Callable[..., Target],
    document_store: DocumentStore,
) -> None:
    """基準のフォルダが上でもスキーマは設定ファイルのフォルダから読む（正常系）。"""
    # 準備
    repo = git_repo(
        {"content/node-docs/brain/note.schema.yaml": "type: object\nrequired: [brain]\n"}
    )
    head = run_git(repo, "rev-parse", "HEAD").strip()
    worktree = tmp_path / "wt"
    run_git(repo, "worktree", "add", "-b", "feat/x", str(worktree))
    documents = [
        DocumentTable(id="notes", paths=["docs/*.yaml"], schema_path="note.schema.yaml")
    ]
    source = make_served_source(
        root=repo,
        config_dir=PurePosixPath("content/node-docs/brain"),
        config=make_source_config(documents=documents),
        is_git=True,
        repo_root=repo,
        schemas={"notes": {"type": "object"}},
    )
    in_worktree = make_target(source, base=worktree, worktree=worktree)
    at_ref = make_target(source, ref="develop", commit=head)
    # 実行
    from_worktree = document_store.schema(in_worktree, "notes")
    from_ref = document_store.schema(at_ref, "notes")
    # 検証
    assert from_worktree["required"] == ["brain"]
    assert from_ref["required"] == ["brain"]

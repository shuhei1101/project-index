# pyright: reportUnknownArgumentType=warning, reportUnknownLambdaType=warning
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.describe.service import describe
from project_index.features.describe.source_checks import SourceChecks
from project_index.features.describe.types import (
    DescribeRequest,
    KindSchemaResult,
    OutsideSource,
    SourceGuideResult,
    SourceListResult,
)
from project_index.features.documents.store import DocumentStore
from project_index.features.history.snapshot import SnapshotStore
from project_index.features.settings.types import SourceEntry, TerminalConfig
from project_index.features.sources.types import DocumentTable, ServedSource, SourceConfig
from project_index.main import build_handlers
from project_index.shared.errors import UnknownKindError, ValidationFailedError

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.sources.registry import SourceRegistry

SCHEMA_TEXT = "description: 規約の文書\ntype: object\n"
# 偽の配信元では警告を求めないので、端末の設定はどの値でもよい
TERMINAL = TerminalConfig(
    file=Path("/w/settings.yaml"),
    version="1",
    clone=Path("/w/clone"),
    state_dir=Path("/w/state"),
    log_dir=Path("/w/state/logs"),
)


@pytest.fixture(autouse=True)
def no_warnings(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """偽の配信元で警告を求めないよう、本物の配信元を使うテスト以外では警告の収集を空にする。"""
    if request.node.name != "test_describe_when_warned":
        monkeypatch.setattr(
            "project_index.features.describe.service.collect_warnings", lambda *args, **kwargs: []
        )


@pytest.fixture
def store(tmp_path: Path) -> DocumentStore:
    """リビジョンの書き出しを `tmp_path` に置く文書のストアを返す。"""
    return DocumentStore(SnapshotStore(tmp_path / "snapshots"))


@pytest.fixture
def folder_source(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
) -> ServedSource:
    """スキーマのファイルと説明書を持つ Git 管理外の配信元 sample を返す。"""
    root = tmp_path / "sample"
    write_files(root, {"schemas/rule.schema.yaml": SCHEMA_TEXT})
    table = DocumentTable(
        id="rules",
        paths=["docs/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"name": "title"},
    )
    config = make_source_config(documents=[table], instructions="着手前に規約を引く")
    return make_served_source(
        id="sample",
        root=root,
        config=config,
        schemas={"rules": {"description": "規約の文書", "type": "object"}},
    )


def _describe(
    source_registry: SourceRegistry, store: DocumentStore, cwd: Path, **request: Any
) -> SourceListResult | SourceGuideResult | KindSchemaResult:
    """作業場所 `cwd` から `describe` を呼ぶ。"""
    return describe(
        DescribeRequest(cwd=str(cwd), **request),
        registry=source_registry,
        store=store,
        terminal=TERMINAL,
        checks=SourceChecks(),
    )


def test_describe(
    store: DocumentStore,
    folder_source: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """使える配信元の一覧（正常系）。"""
    # 準備
    notes = make_served_source(
        id="notes", root=Path("/w/notes"), scope_read=[str(folder_source.root)], scope_write=[]
    )
    other = make_served_source(
        id="other", root=Path("/w/other"), scope_read=["/zzz"], scope_write=[]
    )
    registry = make_registry(folder_source, notes, other)
    # 実行
    result = _describe(registry, store, folder_source.root)
    # 検証
    assert isinstance(result, SourceListResult)
    assert result.workplace.source_id == "sample"
    assert [(item.source_id, item.access, item.current) for item in result.sources] == [
        ("sample", "write", True),
        ("notes", "read", False),
    ]
    assert result.outside_sources is None
    assert result.warnings == []


def test_describe_when_warned(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """使える配信元の警告を添える（正常系）。"""
    # 準備
    config = make_source_dir("sample", unindexed=1)
    terminal = make_terminal_config(sources=[make_entry(str(config), source_id="sample")])
    handlers = build_handlers(terminal)
    handlers.reload_sources(terminal)
    # 実行
    result = describe(
        DescribeRequest(cwd=str(config.parent)),
        registry=handlers.registry,
        store=handlers.store,
        terminal=handlers.terminal,
        checks=handlers.checks,
    )
    # 検証
    assert isinstance(result, SourceListResult)
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("sample: 管理用の YAML に無いファイルが 1 件あります")


def test_describe_when_outside_list(
    store: DocumentStore,
    folder_source: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """作業範囲の外で読める配信元の一覧（正常系）。"""
    # 準備
    notes = make_served_source(
        id="notes", root=Path("/w/notes"), scope_read=[str(folder_source.root)], scope_write=[]
    )
    other = make_served_source(
        id="other",
        root=Path("/w/other"),
        scope_read=["/zzz"],
        scope_write=[],
        outside_read=True,
        config=make_source_config(description="別の配信元"),
    )
    closed = make_served_source(
        id="closed", root=Path("/w/closed"), scope_read=["/yyy"], scope_write=[], outside_read=False
    )
    registry = make_registry(folder_source, notes, other, closed)
    # 実行
    result = _describe(registry, store, folder_source.root, outside_scope=True)
    # 検証
    assert isinstance(result, SourceListResult)
    assert [item.source_id for item in result.sources] == ["sample", "notes"]
    assert result.outside_sources == [OutsideSource(id="other", description="別の配信元")]


def test_describe_when_outside_list_empty(
    store: DocumentStore,
    folder_source: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """作業範囲の外で読める配信元が無い（正常系）。"""
    # 準備
    notes = make_served_source(
        id="notes", root=Path("/w/notes"), scope_read=[str(folder_source.root)], scope_write=[]
    )
    registry = make_registry(folder_source, notes)
    # 実行
    result = _describe(registry, store, folder_source.root, outside_scope=True)
    # 検証
    assert isinstance(result, SourceListResult)
    assert result.outside_sources == []


def test_describe_when_source(
    store: DocumentStore, folder_source: ServedSource, make_registry: Callable[..., SourceRegistry]
) -> None:
    """説明書と種類（正常系）。"""
    # 実行
    result = _describe(make_registry(folder_source), store, folder_source.root, source="sample")
    # 検証
    assert isinstance(result, SourceGuideResult)
    assert result.instructions == "着手前に規約を引く"
    assert [(kind.id, kind.description) for kind in result.kinds] == [("rules", "規約の文書")]


def test_describe_when_kind(
    store: DocumentStore, folder_source: ServedSource, make_registry: Callable[..., SourceRegistry]
) -> None:
    """種類のスキーマ（正常系）。"""
    # 実行
    result = _describe(
        make_registry(folder_source), store, folder_source.root, source="sample", kind="rules"
    )
    # 検証
    assert isinstance(result, KindSchemaResult)
    assert result.schema_text == SCHEMA_TEXT
    assert result.metadata == {"name": "title"}


def test_describe_when_unknown_kind(
    store: DocumentStore, folder_source: ServedSource, make_registry: Callable[..., SourceRegistry]
) -> None:
    """知らない種類（異常系）。"""
    # 実行・検証
    with pytest.raises(UnknownKindError) as exc_info:
        _describe(
            make_registry(folder_source),
            store,
            folder_source.root,
            source="sample",
            kind="no-such-kind",
        )
    assert exc_info.value.kinds == ["rules"]


@pytest.fixture
def worktree_source(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    sample_files: dict[str, str],
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
) -> tuple[ServedSource, Path]:
    """git リポジトリの配信元 sample と、そのワークツリー x を返す。"""
    clone = git_repo(sample_files)
    worktree = clone / ".claude" / "worktrees" / "x"
    run_git(clone, "worktree", "add", "-b", "feat/x", str(worktree))
    source = make_served_source(
        id="sample",
        root=clone,
        config=make_source_config(),
        config_files=[clone / "project-index.yaml"],
        is_git=True,
        repo_root=clone,
        scope_write=[str(clone)],
        worktree_globs=[str(clone / ".claude" / "worktrees" / "*")],
    )
    return source, worktree


def test_describe_when_worktree(
    store: DocumentStore,
    worktree_source: tuple[ServedSource, Path],
    sample_files: dict[str, str],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """ワークツリーの設定で説明する（正常系）。"""
    # 準備
    source, worktree = worktree_source
    (worktree / "project-index.yaml").write_text(
        sample_files["project-index.yaml"] + "instructions: ワークツリーの値\n", encoding="utf-8"
    )
    # 実行
    result = _describe(make_registry(source), store, worktree, source="sample")
    # 検証
    assert isinstance(result, SourceGuideResult)
    assert result.instructions == "ワークツリーの値"


def test_describe_when_worktree_config_invalid(
    store: DocumentStore,
    worktree_source: tuple[ServedSource, Path],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """ワークツリーの設定が検証に通らない（異常系）。"""
    # 準備
    source, worktree = worktree_source
    (worktree / "project-index.yaml").write_text(
        "name: sample\ndocuments:\n  - id: rules\n    schema: schemas/rule.schema.yaml\n",
        encoding="utf-8",
    )
    # 実行・検証
    with pytest.raises(ValidationFailedError) as exc_info:
        _describe(make_registry(source), store, worktree, source="sample")
    assert [v.path for v in exc_info.value.violations] == ["documents[0].paths"]


def test_describe_when_refs_and_worktrees(
    store: DocumentStore,
    worktree_source: tuple[ServedSource, Path],
    run_git: Callable[..., str],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """ブランチとワークツリー（正常系）。"""
    # 準備
    source, _ = worktree_source
    run_git(source.root, "tag", "-a", "v0.1.0", "-m", "release")
    # 実行
    result = _describe(make_registry(source), store, source.root, source="sample")
    # 検証
    assert isinstance(result, SourceGuideResult)
    assert result.refs is not None
    assert {"develop", "feat/x"} <= set(result.refs["branches"])
    assert result.refs["tags"] == ["v0.1.0"]
    assert result.worktrees is not None
    assert result.worktrees[0].branch == "feat/x"

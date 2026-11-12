from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.access import service as service_module
from project_index.features.access.service import (
    access_of,
    available_sources,
    current_source,
    describe_workplace,
    find_worktree,
    outside_readable_sources,
    resolve_read_targets,
    resolve_write_target,
)
from project_index.features.access.types import SourceAccess
from project_index.features.history.types import ResolvedRef
from project_index.shared.errors import (
    InvalidArgumentError,
    RefNotFoundError,
    SourceNotReadableError,
    SourceNotWritableError,
    TargetIsCloneError,
    WorktreeNotMatchedError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.sources.types import ServedSource, SourceConfig

WORKTREE_GLOBS = ["/r/.claude/worktrees/*"]


@pytest.fixture
def sample(make_served_source: Callable[..., ServedSource]) -> ServedSource:
    """/r のクローン本体を持つ Git の配信元 sample を返す。"""
    return make_served_source(
        id="sample",
        root=Path("/r"),
        config_files=[Path("/r/project-index.yaml")],
        is_git=True,
        repo_root=Path("/r"),
        scope_write=["/r"],
        worktree_globs=WORKTREE_GLOBS,
    )


def test_find_worktree(sample: ServedSource) -> None:
    """ワークツリーの中のフォルダ（正常系）。"""
    # 実行
    result = find_worktree(sample, Path("/r/.claude/worktrees/x/docs"))
    # 検証
    assert result == Path("/r/.claude/worktrees/x")


def test_find_worktree_when_outside_repo(
    make_served_source: Callable[..., ServedSource],
) -> None:
    """リポジトリの外のワークツリー（正常系）。"""
    # 準備
    source = make_served_source(worktree_globs=["/repo/aituber-develop"])
    # 実行
    result = find_worktree(source, Path("/repo/aituber-develop/src"))
    # 検証
    assert result == Path("/repo/aituber-develop")


def test_find_worktree_when_clone(sample: ServedSource) -> None:
    """クローン本体（正常系）。"""
    # 実行
    result = find_worktree(sample, Path("/r/docs"))
    # 検証
    assert result is None


def test_access_of_when_write(sample: ServedSource) -> None:
    """読み書き（正常系）。"""
    # 実行
    result = access_of(sample, Path("/r"))
    # 検証
    assert result == "write"


def test_access_of_when_read(make_served_source: Callable[..., ServedSource]) -> None:
    """読み取りだけ（正常系）。"""
    # 準備
    source = make_served_source(scope_read=["/a/**"], scope_write=[])
    # 実行
    result = access_of(source, Path("/a/b"))
    # 検証
    assert result == "read"


def test_access_of_when_worktree(sample: ServedSource) -> None:
    """ワークツリーは配信元のフォルダとみなす（正常系）。"""
    # 実行
    result = access_of(sample, Path("/r/.claude/worktrees/x"))
    # 検証
    assert result == "write"


def test_access_of_when_none(sample: ServedSource) -> None:
    """当たらない（正常系）。"""
    # 実行
    outside = access_of(sample, Path("/other"))
    without_cwd = access_of(sample, None)
    # 検証
    assert outside is None
    assert without_cwd is None


def test_current_source(make_served_source: Callable[..., ServedSource]) -> None:
    """一番深い配信元（正常系）。"""
    # 準備
    shallow = make_served_source(id="a", root=Path("/r"))
    deep = make_served_source(id="b", root=Path("/r/tmp/ws"))
    # 実行
    result = current_source([shallow, deep], Path("/r/tmp/ws/x"))
    # 検証
    assert result == (deep, None)


def test_current_source_when_worktree(sample: ServedSource) -> None:
    """ワークツリーの中（正常系）。"""
    # 実行
    result = current_source([sample], Path("/r/.claude/worktrees/x/docs"))
    # 検証
    assert result == (sample, Path("/r/.claude/worktrees/x"))


def test_current_source_when_none(sample: ServedSource) -> None:
    """どの配信元の中でもない（正常系）。"""
    # 実行
    result = current_source([sample], Path("/other"))
    # 検証
    assert result is None


def test_available_sources(
    make_served_source: Callable[..., ServedSource],
    make_source_config: Callable[..., SourceConfig],
    make_registry: Callable[..., Any],
) -> None:
    """権限と作業中を付ける（正常系）。"""
    # 準備
    sample = make_served_source(
        id="sample",
        root=Path("/w/sample"),
        scope_write=["/w/sample"],
        config=make_source_config(description="サンプル"),
    )
    notes = make_served_source(
        id="notes",
        root=Path("/w/notes"),
        scope_read=["/w/sample"],
        scope_write=[],
        config=make_source_config(description="メモ"),
    )
    other = make_served_source(
        id="other", root=Path("/w/other"), scope_read=["/zzz"], scope_write=[]
    )
    registry = make_registry(sample, notes, other)
    # 実行
    result = available_sources("/w/sample", registry=registry)
    # 検証
    assert result == [
        SourceAccess(source_id="sample", access="write", current=True, description="サンプル"),
        SourceAccess(source_id="notes", access="read", current=False, description="メモ"),
    ]


def test_available_sources_when_no_cwd(
    sample: ServedSource, make_registry: Callable[..., Any]
) -> None:
    """作業場所が無い（正常系）。"""
    # 準備
    registry = make_registry(sample)
    # 実行
    result = available_sources(None, registry=registry)
    # 検証
    assert result == []


def test_outside_readable_sources(
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
) -> None:
    """scope に当たらず outside_read が真の配信元だけを並べる（正常系）。"""
    # 準備
    sample = make_served_source(id="sample", root=Path("/w/sample"), scope_write=["/w/sample"])
    notes = make_served_source(
        id="notes", root=Path("/w/notes"), scope_read=["/w/sample"], scope_write=[]
    )
    other = make_served_source(
        id="other", root=Path("/w/other"), scope_read=["/zzz"], scope_write=[], outside_read=True
    )
    closed = make_served_source(
        id="closed", root=Path("/w/closed"), scope_read=["/yyy"], scope_write=[], outside_read=False
    )
    registry = make_registry(sample, notes, other, closed)
    # 実行
    result = outside_readable_sources("/w/sample", registry=registry)
    # 検証
    assert [item.id for item in result] == ["other"]


def test_outside_readable_sources_when_no_cwd(
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
) -> None:
    """作業場所が無い（正常系）。"""
    # 準備
    other = make_served_source(
        id="other", root=Path("/w/other"), scope_read=["/zzz"], scope_write=[], outside_read=True
    )
    # 実行
    result = outside_readable_sources(None, registry=make_registry(other))
    # 検証
    assert [item.id for item in result] == ["other"]


def test_describe_workplace(sample: ServedSource, make_registry: Callable[..., Any]) -> None:
    """ワークツリーの中（正常系）。"""
    # 準備
    registry = make_registry(sample)
    # 実行
    result = describe_workplace("/r/.claude/worktrees/x/docs", registry=registry)
    # 検証
    assert result.source_id == "sample"
    assert result.worktree == Path("/r/.claude/worktrees/x")


def test_resolve_read_targets(sample: ServedSource, make_registry: Callable[..., Any]) -> None:
    """作業中の配信元は作業ツリーを読む（正常系）。"""
    # 準備
    registry = make_registry(sample)
    # 実行
    result = resolve_read_targets(registry=registry, cwd="/r")
    # 検証
    assert len(result) == 1
    assert result[0].source is sample
    assert result[0].ref is None
    assert result[0].base == Path("/r")


RESOLVED_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def test_resolve_read_targets_when_other_source(
    sample: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """作業中でない Git の配信元は既定のリビジョン（正常系）。"""
    # 準備
    notes = make_served_source(
        id="notes",
        root=Path("/n"),
        is_git=True,
        repo_root=Path("/n"),
        scope_read=["/r"],
        scope_write=[],
    )
    registry = make_registry(sample, notes)
    calls: list[tuple[Path, str, str]] = []

    def fake_resolve_ref(repo_root: Path, ref: str, *, date_base: str, **_: Any) -> ResolvedRef:
        calls.append((repo_root, ref, date_base))
        return ResolvedRef(
            input=ref,
            commit=RESOLVED_COMMIT,
            date=datetime.fromisoformat("2026-10-01T12:00:00+09:00"),
        )

    monkeypatch.setattr(service_module, "resolve_ref", fake_resolve_ref, raising=False)
    # 実行
    result = resolve_read_targets(registry=registry, source="notes", cwd="/r")
    # 検証
    assert result[0].ref == "develop"
    assert result[0].commit == RESOLVED_COMMIT
    assert calls == [(Path("/n"), "develop", "develop")]


def test_resolve_read_targets_when_ref_not_found(
    sample: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解けない ref（異常系）。"""
    # 準備
    notes = make_served_source(
        id="notes",
        root=Path("/n"),
        is_git=True,
        repo_root=Path("/n"),
        scope_read=["/r"],
        scope_write=[],
    )
    registry = make_registry(sample, notes)

    def fake_resolve_ref(repo_root: Path, ref: str, *, date_base: str, **_: Any) -> ResolvedRef:
        raise RefNotFoundError(
            message=f"ref={ref} を commit に解決できません", argument="ref", value=ref
        )

    monkeypatch.setattr(service_module, "resolve_ref", fake_resolve_ref, raising=False)
    # 実行・検証
    with pytest.raises(RefNotFoundError):
        resolve_read_targets(registry=registry, source="notes", ref="nope", cwd="/r")


def test_resolve_read_targets_when_worktree_cwd(
    make_served_source: Callable[..., ServedSource], make_registry: Callable[..., Any]
) -> None:
    """ワークツリーの中から読む（正常系）。"""
    # 準備
    source = make_served_source(
        id="sample",
        root=Path("/r/docs-src"),
        is_git=True,
        repo_root=Path("/r"),
        scope_write=["/r/docs-src"],
        worktree_globs=WORKTREE_GLOBS,
    )
    registry = make_registry(source)
    # 実行
    result = resolve_read_targets(registry=registry, cwd="/r/.claude/worktrees/x")
    # 検証
    assert result[0].base == Path("/r/.claude/worktrees/x/docs-src")
    assert result[0].worktree == Path("/r/.claude/worktrees/x")


def test_resolve_read_targets_when_all(
    sample: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
) -> None:
    """`*` は読める配信元だけ（正常系）。"""
    # 準備
    notes = make_served_source(id="notes", root=Path("/n"), scope_read=["/r"], scope_write=[])
    other = make_served_source(id="other", root=Path("/o"), scope_read=["/zzz"], scope_write=[])
    registry = make_registry(sample, notes, other)
    # 実行
    result = resolve_read_targets(registry=registry, source="*", cwd="/r")
    # 検証
    assert [target.source.id for target in result] == ["sample", "notes"]


def test_resolve_read_targets_when_not_readable(
    sample: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
) -> None:
    """権限が無い（異常系）。"""
    # 準備
    other = make_served_source(id="other", root=Path("/o"), scope_read=["/zzz"], scope_write=[])
    registry = make_registry(sample, other)
    # 実行・検証
    with pytest.raises(SourceNotReadableError) as exc_info:
        resolve_read_targets(registry=registry, source="other", cwd="/r")
    assert [item.source_id for item in exc_info.value.available] == ["sample"]


def test_resolve_read_targets_when_worktree_not_matched(
    sample: ServedSource, make_registry: Callable[..., Any]
) -> None:
    """ワークツリーに当たらない（異常系）。"""
    # 準備
    registry = make_registry(sample)
    # 実行・検証
    with pytest.raises(WorktreeNotMatchedError) as exc_info:
        resolve_read_targets(registry=registry, worktree="/tmp/x", cwd="/r")
    assert exc_info.value.patterns == sample.worktree_globs


def test_resolve_read_targets_when_ref_on_folder(
    make_served_source: Callable[..., ServedSource], make_registry: Callable[..., Any]
) -> None:
    """Git の管理外に ref（異常系）。"""
    # 準備
    notes = make_served_source(
        id="notes", root=Path("/n"), is_git=False, scope_read=["/r"], scope_write=[]
    )
    registry = make_registry(notes)
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        resolve_read_targets(registry=registry, source="notes", ref="main", cwd="/r")
    assert [v.path for v in exc_info.value.violations] == ["ref"]


def test_resolve_write_target(sample: ServedSource, make_registry: Callable[..., Any]) -> None:
    """ワークツリーへ書く（正常系）。"""
    # 準備
    registry = make_registry(sample)
    # 実行
    result = resolve_write_target(registry=registry, cwd="/r/.claude/worktrees/x/docs")
    # 検証
    assert result.worktree == Path("/r/.claude/worktrees/x")
    assert result.access == "write"


def test_resolve_write_target_when_folder(
    make_served_source: Callable[..., ServedSource], make_registry: Callable[..., Any]
) -> None:
    """Git の管理外はフォルダへ書く（正常系）。"""
    # 準備
    notes = make_served_source(id="notes", root=Path("/n"), is_git=False, scope_write=["/c"])
    registry = make_registry(notes)
    # 実行
    result = resolve_write_target(registry=registry, source="notes", cwd="/c")
    # 検証
    assert result.base == Path("/n")
    assert result.worktree is None


def test_resolve_write_target_when_read_only(
    make_served_source: Callable[..., ServedSource], make_registry: Callable[..., Any]
) -> None:
    """読み取りだけ（異常系）。"""
    # 準備
    notes = make_served_source(id="notes", root=Path("/n"), scope_read=["/c"], scope_write=[])
    registry = make_registry(notes)
    # 実行・検証
    with pytest.raises(SourceNotWritableError) as exc_info:
        resolve_write_target(registry=registry, source="notes", cwd="/c")
    assert [(item.source_id, item.access) for item in exc_info.value.available] == [
        ("notes", "read")
    ]


def test_resolve_write_target_when_clone(
    sample: ServedSource, make_registry: Callable[..., Any]
) -> None:
    """クローン本体へは書かない（異常系）。"""
    # 準備
    registry = make_registry(sample)
    # 実行・検証
    with pytest.raises(TargetIsCloneError) as exc_info:
        resolve_write_target(registry=registry, cwd="/r")
    assert exc_info.value.clone == "/r"


def test_resolve_read_targets_when_outside_scope(
    sample: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """作業範囲の外を参考に読む（正常系）。"""
    # 準備
    other = make_served_source(
        id="other", root=Path("/o"), scope_read=["/zzz"], scope_write=[], outside_read=True
    )
    registry = make_registry(sample, other)
    # 実行
    with caplog.at_level(logging.INFO):
        result = resolve_read_targets(
            registry=registry, source="other", cwd="/r", outside_scope=True
        )
    # 検証
    messages = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
    assert [(target.source.id, target.outside_scope, target.access) for target in result] == [
        ("other", True, "read")
    ]
    assert len([message for message in messages if "/r" in message and "other" in message]) == 1


def test_resolve_read_targets_when_outside_scope_in_scope(
    sample: ServedSource, make_registry: Callable[..., Any], caplog: pytest.LogCaptureFixture
) -> None:
    """scope に当たる配信元には付けない（正常系）。"""
    # 準備
    registry = make_registry(sample)
    # 実行
    with caplog.at_level(logging.INFO):
        result = resolve_read_targets(
            registry=registry, source="sample", cwd="/r", outside_scope=True
        )
    # 検証
    assert result[0].outside_scope is False
    assert [record for record in caplog.records if record.levelno == logging.INFO] == []


def test_resolve_read_targets_when_outside_scope_all(
    sample: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
) -> None:
    """`*` には効かない（正常系）。"""
    # 準備
    other = make_served_source(
        id="other", root=Path("/o"), scope_read=["/zzz"], scope_write=[], outside_read=True
    )
    registry = make_registry(sample, other)
    # 実行
    result = resolve_read_targets(registry=registry, source="*", cwd="/r", outside_scope=True)
    # 検証
    assert [target.source.id for target in result] == ["sample"]


def test_resolve_read_targets_when_outside_read_disabled(
    sample: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
) -> None:
    """外から読むのを断る配信元（異常系）。"""
    # 準備
    other = make_served_source(
        id="other", root=Path("/o"), scope_read=["/zzz"], scope_write=[], outside_read=False
    )
    registry = make_registry(sample, other)
    # 実行・検証
    with pytest.raises(SourceNotReadableError, match="other はこの作業場所") as exc_info:
        resolve_read_targets(registry=registry, source="other", cwd="/r", outside_scope=True)
    assert [step for step in exc_info.value.next_steps if "outside_scope" in step] == []


def test_resolve_read_targets_when_not_readable_guides_outside(
    sample: ServedSource,
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., Any],
) -> None:
    """外から読めることを案内する（異常系）。"""
    # 準備
    other = make_served_source(
        id="other", root=Path("/o"), scope_read=["/zzz"], scope_write=[], outside_read=True
    )
    registry = make_registry(sample, other)
    # 実行・検証
    with pytest.raises(SourceNotReadableError, match="other はこの作業場所") as exc_info:
        resolve_read_targets(registry=registry, source="other", cwd="/r")
    assert len([step for step in exc_info.value.next_steps if "outside_scope: true" in step]) == 1

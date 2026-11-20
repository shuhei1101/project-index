from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.access.types import Target
from project_index.features.read.paths import read_target

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.sources.registry import SourceRegistry
    from project_index.features.sources.types import ServedSource, SourceConfig


def test_read_target(
    git_repo: Callable[..., Path],
    run_git: Callable[..., str],
    make_source_config: Callable[..., SourceConfig],
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """既定のリビジョン（正常系）。"""
    # 準備
    root = git_repo({"docs/a.yaml": "id: a\n"})
    source = make_served_source(
        id="sample",
        root=root,
        is_git=True,
        repo_root=root,
        config=make_source_config(default_ref="develop"),
    )
    commit = run_git(root, "rev-parse", "develop").strip()
    # 実行
    target, resolved = read_target("sample", None, registry=make_registry(source))
    # 検証
    assert isinstance(target, Target)
    assert target.ref == "develop"
    assert target.commit == commit
    assert resolved is not None
    assert resolved.commit == commit


def test_read_target_when_not_git(
    make_served_source: Callable[..., ServedSource],
    make_registry: Callable[..., SourceRegistry],
) -> None:
    """Git 管理外（正常系）。"""
    # 準備
    source = make_served_source(id="notes", is_git=False)
    # 実行
    target, resolved = read_target("notes", "main", registry=make_registry(source))
    # 検証
    assert target.ref is None
    assert resolved is None

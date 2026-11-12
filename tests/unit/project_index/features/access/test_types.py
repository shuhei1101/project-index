from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from project_index.features.access.types import Target

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.sources.types import ServedSource


def test_target_config_base(make_served_source: Callable[..., ServedSource]) -> None:
    """ワークツリーの中の設定ファイルのフォルダ（正常系）。"""
    # 準備
    source = make_served_source(
        root=Path("/r"), config_dir=PurePosixPath("content/node-docs/brain")
    )
    target = Target(source, Path("/wt"), None, Path("/wt"), "write")
    # 実行
    result = target.config_base
    # 検証
    assert result == Path("/wt/content/node-docs/brain")

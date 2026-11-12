from __future__ import annotations

from typing import Any

from project_index.features.sources.merge import merge_configs


def test_merge_configs() -> None:
    """値を上書きしテーブルを行ごとに重ねる（正常系）。"""
    # 準備
    values: list[dict[str, Any]] = [
        {"description": "a", "documents": [{"id": "x", "paths": ["a/*"]}]},
        {
            "description": "b",
            "documents": [{"id": "x", "paths": ["b/*"]}, {"id": "y", "paths": ["c"]}],
        },
    ]
    # 実行
    result = merge_configs(values)
    # 検証
    assert result["description"] == "b"
    assert result["documents"] == [{"id": "x", "paths": ["b/*"]}, {"id": "y", "paths": ["c"]}]


def test_merge_configs_when_nested_object() -> None:
    """オブジェクトを再帰で重ねる（正常系）。"""
    # 準備
    values: list[dict[str, Any]] = [
        {"visibility": {"key": "v", "public": ["p"]}},
        {"visibility": {"public": ["q"]}},
    ]
    # 実行
    result = merge_configs(values)
    # 検証
    assert result["visibility"] == {"key": "v", "public": ["q"]}


def test_merge_configs_when_value_array() -> None:
    """値の配列は置き換える（正常系）。"""
    # 準備
    values: list[dict[str, Any]] = [{"worktrees": ["a", "b"]}, {"worktrees": ["c"]}]
    # 実行
    result = merge_configs(values)
    # 検証
    assert result["worktrees"] == ["c"]


def test_merge_configs_when_single() -> None:
    """1 つだけはそのまま（正常系）。"""
    # 準備
    value = {"name": "a", "documents": [{"id": "x", "paths": ["a/*"]}]}
    # 実行
    result = merge_configs([value])
    # 検証
    assert result == value
    assert result is not value

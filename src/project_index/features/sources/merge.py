"""配信元の設定の YAML のマージ。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

TABLE_KEYS = frozenset({"documents", "validators", "converters", "generators"})


def _merge_table(base: list[Any], over: list[Any]) -> list[Any]:
    """`id` が同じ行は後の行で置き換え、新しい `id` の行は末尾に追加する。"""
    result = list(base)
    positions = {
        row["id"]: index
        for index, row in enumerate(result)
        if isinstance(row, dict) and "id" in row
    }
    for row in over:
        row_id = row.get("id") if isinstance(row, dict) else None
        if row_id is not None and row_id in positions:
            result[positions[row_id]] = copy.deepcopy(row)
            continue
        result.append(copy.deepcopy(row))
        if row_id is not None:
            positions[row_id] = len(result) - 1
    return result


def _merge_dict(base: dict[str, Any], over: dict[str, Any], *, top: bool) -> dict[str, Any]:
    """辞書を再帰で重ねる（最上位のテーブルのキーは行ごとに重ねる）。"""
    result = dict(base)
    for key, value in over.items():
        current = result.get(key)
        if top and key in TABLE_KEYS and isinstance(current, list) and isinstance(value, list):
            result[key] = _merge_table(current, value)
        elif isinstance(current, dict) and isinstance(value, dict):
            result[key] = _merge_dict(current, value, top=False)
        else:
            result[key] = copy.deepcopy(value)
    return result


def merge_configs(values: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """配信元の設定の YAML の値を上から順に重ねる。"""
    result = copy.deepcopy(values[0])
    for value in values[1:]:
        result = _merge_dict(result, value, top=True)
    return result

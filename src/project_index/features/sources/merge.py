"""配信元の設定の YAML のマージ。"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

TABLE_KEYS = frozenset({"documents", "validators", "converters", "generators"})


def _merge_table(base: list[object], over: list[object]) -> list[object]:
    """`id` が同じ行は後の行で置き換え、新しい `id` の行は末尾に追加する。"""
    result = list(base)
    positions = {
        row["id"]: index for index, row in enumerate(result) if is_dict(row) and "id" in row
    }
    for row in over:
        row_id = row.get("id") if is_dict(row) else None
        if row_id is not None and row_id in positions:
            result[positions[row_id]] = copy.deepcopy(row)
            continue
        result.append(copy.deepcopy(row))
        if row_id is not None:
            positions[row_id] = len(result) - 1
    return result


def _merge_dict[K](
    base: Mapping[K, object], over: Mapping[K, object], *, top: bool
) -> dict[K, object]:
    """辞書を再帰で重ねる（最上位のテーブルのキーは行ごとに重ねる）。"""
    result = dict(base)
    for key, value in over.items():
        current = result.get(key)
        if top and key in TABLE_KEYS and is_list(current) and is_list(value):
            result[key] = _merge_table(current, value)
        elif is_dict(current) and is_dict(value):
            result[key] = _merge_dict(current, value, top=False)
        else:
            result[key] = copy.deepcopy(value)
    return result


def merge_configs(values: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """配信元の設定の YAML の値を上から順に重ねる。"""
    result: dict[str, Any] = copy.deepcopy(values[0])
    for value in values[1:]:
        result = _merge_dict(result, value, top=True)
    return result

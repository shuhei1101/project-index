"""YAML・JSON から読んだ型の決まっていない値を、辞書・配列として絞り込む。"""

from __future__ import annotations

from typing import TypeIs


def is_dict(value: object) -> TypeIs[dict[object, object]]:
    """値が辞書かを判定し、真なら `dict[object, object]` に絞り込む。"""
    return isinstance(value, dict)


def is_list(value: object) -> TypeIs[list[object]]:
    """値が配列かを判定し、真なら `list[object]` に絞り込む。"""
    return isinstance(value, list)

"""`replace_text` の文書の配下の文字列の値の置換。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.documents.fields import get_field
from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Collection, MutableMapping, MutableSequence, Sequence

    from ruamel.yaml.comments import CommentedMap


def _replace_slot(
    container: MutableMapping[object, object] | MutableSequence[object],
    key: object,
    old: str,
    new: str,
) -> int:
    """入れ物の 1 つの値を置換するか、配下をたどって、置換の件数を返す。"""
    value = container[key]  # type: ignore[index]
    if isinstance(value, str):
        found = value.count(old)
        if found:
            replaced = value.replace(old, new)
            kind = type(value)
            container[key] = replaced if kind is str else kind(replaced)  # type: ignore[index]
        return found
    return _replace_node(value, old, new)


def _replace_node(node: object, old: str, new: str) -> int:
    """辞書の値と配列の要素をたどって置換し、件数を返す（辞書のキーは変えない）。"""
    if is_dict(node):
        mapping: MutableMapping[object, object] = node
        return sum(_replace_slot(mapping, key, old, new) for key in list(mapping))
    if is_list(node):
        sequence: MutableSequence[object] = node
        return sum(_replace_slot(sequence, position, old, new) for position in range(len(sequence)))
    return 0


def replace_in_values(
    content: CommentedMap,
    *,
    old: str,
    new: str,
    fields: Sequence[str] | None,
    skip: Collection[str],
) -> int:
    """文書 1 件の内容の文字列の値の `old` をその場で `new` にし、置換の件数を返す。"""
    if fields is None:
        return sum(
            _replace_slot(content, key, old, new) for key in list(content) if key not in skip
        )
    count = 0
    for path in fields:
        parent_path, _, last = path.rpartition(".")
        parent = content if not parent_path else get_field(content, parent_path)
        if is_dict(parent) and last in parent and last not in (skip if not parent_path else ()):
            count += _replace_slot(parent, last, old, new)
    return count

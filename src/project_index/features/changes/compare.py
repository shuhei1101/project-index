"""内容の比較。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import difflib
import unicodedata
from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING, Any

from project_index.features.search.filters import compile_regex, normalize

if TYPE_CHECKING:
    from project_index.features.changes.types import ContainsQuery

MATCH_KEYS = ("id", "name")
GAP_LINE = "…"


def _match_key(items: list[Any]) -> str | None:
    """要素を突き合わせるキー（全ての要素が持つ `id` か `name`）を返す。"""
    if not items or not all(isinstance(item, Mapping) for item in items):
        return None
    for key in MATCH_KEYS:
        values = [item.get(key) for item in items]
        if all(value is not None for value in values) and len(set(map(str, values))) == len(values):
            return key
    return None


def _walk(before: Any, after: Any, path: str, found: dict[str, tuple[Any, Any]]) -> None:  # noqa: ANN401
    """2 つの値を再帰で比べ、違うパスを `found` に入れる。"""
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        keys = [*after, *(key for key in before if key not in after)]
        for key in keys:
            _walk(before.get(key), after.get(key), f"{path}.{key}" if path else str(key), found)
        return
    if isinstance(before, list) and isinstance(after, list):
        key = _match_key([*before, *after]) if before or after else None
        # 前後のどちらかが空でも、残る側のキーで突き合わせられる
        key = key or _match_key(before) or _match_key(after)
        if key is not None:
            by_before = {str(item[key]): item for item in before}
            by_after = {str(item[key]): item for item in after}
            for name in [*by_after, *(name for name in by_before if name not in by_after)]:
                _walk(by_before.get(name), by_after.get(name), f"{path}[{name}]", found)
            return
    if before != after:
        found[path] = (before, after)


def changed_keys(
    before: Mapping[str, Any], after: Mapping[str, Any], *, ignore: Collection[str] = ()
) -> dict[str, tuple[Any, Any]]:
    """2 つの内容を比べ、変わったキーのパスと前後の値を返す。"""
    found: dict[str, tuple[Any, Any]] = {}
    keys = [*after, *(key for key in before if key not in after)]
    for key in keys:
        if key in ignore:
            continue
        _walk(before.get(key), after.get(key), str(key), found)
    return found


def diff_lines(before: str, after: str) -> str:
    """2 つの文字列の違う行を、git と同じ `-`・`+` の行にする。"""
    lines: list[str] = []
    hunks = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            hunks += 1
            if hunks > 1:
                lines.append(GAP_LINE)
            continue
        lines.append(f"{line[0]} {line[1:]}")
    return "\n".join(lines)


def count_occurrences(text: str, query: ContainsQuery) -> int:
    """文字列の中の語の出現数（正規表現なら当たった数）を返す。"""
    if query.regex:
        pattern = compile_regex(query.value, case_sensitive=query.case_sensitive)
        # 区別しないときは文書の値だけを NFKC にする（パターンには正規化をかけない）
        target = text if query.case_sensitive else unicodedata.normalize("NFKC", text)
        return len(list(pattern.finditer(target)))
    if query.case_sensitive:
        return text.count(query.value)
    return normalize(text).count(normalize(query.value))

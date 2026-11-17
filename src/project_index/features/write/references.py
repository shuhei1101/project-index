"""`rename` の改名後のパスと、参照元の旧 ID・旧パスを指す箇所の書き換え。"""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING, cast

from project_index.features.write.types import ReferenceChange
from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Collection, MutableMapping, MutableSequence

    from ruamel.yaml.comments import CommentedMap

# Markdown のリンクの先（`](...)`）
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")


def renamed_path(path: str, *, old_id: str, new_id: str) -> str | None:
    """`new_path` を省いた `rename` の改名後のファイルのパスを決める。"""
    folder, name = posixpath.split(path)
    stem, dot, rest = name.partition(".")
    if stem != old_id:
        return None
    return posixpath.join(folder, f"{new_id}{dot}{rest}")


def _same_kind(original: str, value: str) -> str:
    """元のスカラーの型（引用符の種類）を保った文字列を返す。"""
    kind = type(original)
    return value if kind is str else kind(value)


def _relative(target: str, base_dir: str) -> str:
    """`base_dir` から `target` を指す相対のパス。"""
    return posixpath.relpath(target, base_dir or ".")


def _resolves_to(value: str, base_dir: str, path: str) -> bool:
    """`base_dir` から解いた `value` が `path` になるか。"""
    if not value or value.startswith(("/", "#")) or "://" in value or value.startswith("id:"):
        return False
    return posixpath.normpath(posixpath.join(base_dir, value)) == path


def _moved_value(value: str, base_dir: str, moved: tuple[str, str]) -> str:
    """改名前のパスを指す相対の値を、改名後のパスを指す値にする（`./` は保つ）。"""
    new = _relative(moved[1], base_dir)
    return f"./{new}" if value.startswith("./") and not new.startswith("../") else new


type _Piece = tuple[str, str]


class _Rewriter:
    """文字列の値 1 つを書き換え、書き換えた箇所ごとの前後を集める規則。"""

    def __init__(
        self, *, old_id: str, new_id: str, moved: tuple[str, str] | None, base_dir: str
    ) -> None:
        self.old_id = old_id
        self.new_id = new_id
        self.moved = moved
        self.base_dir = base_dir
        self.id_link = re.compile(rf"id:{re.escape(old_id)}(?=[#)\"'\s]|$)")

    def __call__(self, value: str) -> tuple[str, list[_Piece]]:
        pieces: list[_Piece] = []
        result = value
        if self.old_id != self.new_id:
            if result.startswith(f"{self.old_id}#"):
                after = f"{self.new_id}#{result[len(self.old_id) + 1 :]}"
                pieces.append((result, after))
                result = after
            found = len(self.id_link.findall(result))
            result = self.id_link.sub(f"id:{self.new_id}", result)
            pieces += [(f"id:{self.old_id}", f"id:{self.new_id}")] * found
        if self.moved is not None:
            if _resolves_to(result, self.base_dir, self.moved[0]):
                after = _moved_value(result, self.base_dir, self.moved)
                return after, [*pieces, (result, after)]
            links: list[_Piece] = []
            result = LINK_TARGET.sub(lambda match: self._link(match, links), result)
            pieces += links
        return result, pieces

    def _link(self, match: re.Match[str], links: list[_Piece]) -> str:
        target = match.group(1)
        if self.moved is None or not _resolves_to(target, self.base_dir, self.moved[0]):
            return match.group(0)
        after = _moved_value(target, self.base_dir, self.moved)
        links.append((target, after))
        return f"]({after})"


def _visit(
    node: object,
    path: str,
    rewrite: _Rewriter,
    changes: list[ReferenceChange],
) -> None:
    """辞書の値と配列の要素をたどり、文字列の値を書き換える。"""
    if is_dict(node):
        mapping: MutableMapping[object, object] = node
        for key in list(mapping):
            _rewrite_slot(mapping, key, f"{path}.{key}" if path else str(key), rewrite, changes)
    elif is_list(node):
        sequence: MutableSequence[object] = node
        for position in range(len(sequence)):
            _rewrite_slot(sequence, position, f"{path}[{position}]", rewrite, changes)


def _rewrite_slot(
    container: MutableMapping[object, object] | MutableSequence[object],
    key: object,
    path: str,
    rewrite: _Rewriter,
    changes: list[ReferenceChange],
) -> None:
    """入れ物の 1 つの値を書き換えるか、配下をたどる。"""
    value = cast("object", container[key])  # type: ignore[index]
    if isinstance(value, str):
        after, pieces = rewrite(value)
        if pieces:
            container[key] = _same_kind(value, after)  # type: ignore[index]
            changes.extend(ReferenceChange(path=path, before=b, after=a) for b, a in pieces)
        return
    _visit(value, path, rewrite, changes)


def rewrite_references(
    content: CommentedMap,
    *,
    related_column: str,
    old_id: str,
    new_id: str,
    moved: tuple[str, str] | None,
    base_dir: str,
    skip: Collection[str],
) -> list[ReferenceChange]:
    """文書 1 件の内容のうち、旧 ID・旧パスを指す箇所をその場で書き換え、書き換えた箇所を返す。"""
    changes: list[ReferenceChange] = []
    rows = content.get(related_column)
    if is_list(rows) and old_id != new_id:
        for position, row in enumerate(rows):
            if not is_dict(row):
                continue
            mapping: MutableMapping[object, object] = row
            to = mapping.get("to")
            if isinstance(to, str) and to == old_id and "source" not in mapping:
                mapping["to"] = _same_kind(to, new_id)
                changes.append(
                    ReferenceChange(
                        path=f"{related_column}[{position}].to", before=old_id, after=new_id
                    )
                )
    rewrite = _Rewriter(old_id=old_id, new_id=new_id, moved=moved, base_dir=base_dir)
    for key in list(content):
        if key in skip:
            continue
        _rewrite_slot(content, key, str(key), rewrite, changes)
    return changes

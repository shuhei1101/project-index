"""`related` のたどり。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from project_index.features.documents.types import Document
from project_index.features.related.types import RelatedLink
from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Sequence


def related_links(document: Document) -> list[RelatedLink]:
    """文書のメタデータの `related` を関連の行の並びにする。"""
    rows: object = document.metadata.get("related")
    if not is_list(rows):
        return []
    links: list[RelatedLink] = []
    for row in rows:
        to = row.get("to") if is_dict(row) else None
        if not is_dict(row) or not isinstance(to, str):
            continue
        source = row.get("source")
        links.append(
            RelatedLink(
                to=to,
                type=str(row.get("type") or ""),
                source=source if isinstance(source, str) else None,
            )
        )
    return links


type Found = tuple[Document, int, str, str, Literal["out", "in"]]


@dataclass
class _Walk:
    """幅優先のたどりの途中の状態（たどった文書・見つけた文書・注意書き）。"""

    documents: Mapping[str, Document]
    resolve_other: Callable[[str, str], Document | None]
    reverse: dict[str, list[tuple[Document, RelatedLink]]]
    visited: set[str]
    found: list[Found] = field(default_factory=list[Found])
    notes: list[str] = field(default_factory=list[str])

    def _note(self, note: str) -> None:
        """同じ注意書きを重ねずに足す。"""
        if note not in self.notes:
            self.notes.append(note)

    def _target(self, link: RelatedLink) -> tuple[str, Document | None]:
        """関連の先の文書と、たどった印のキーを返す（無ければ注意書きを足して `None`）。"""
        if link.source is not None:
            key = f"{link.source}:{link.to}"
            target = self.resolve_other(link.source, link.to)
            if target is None:
                self._note(f"{key} は参照できないので除きました")
            return key, target
        target = self.documents.get(link.to)
        if target is None:
            self._note(f"{link.to} がありません")
        return link.to, target

    def out(self, current: Document, level: int) -> list[Document]:
        """`current` の `related` が指す文書をたどる。"""
        following: list[Document] = []
        for link in related_links(current):
            key, target = self._target(link)
            if target is None or key in self.visited:
                continue
            self.visited.add(key)
            self.found.append((target, level, current.id, link.type, "out"))
            following.append(target)
        return following

    def into(self, current: Document, level: int) -> list[Document]:
        """`current` を `related` で指す文書をたどる。"""
        following: list[Document] = []
        for referrer, link in self.reverse.get(current.id, []):
            if referrer.id in self.visited:
                continue
            self.visited.add(referrer.id)
            self.found.append((referrer, level, current.id, link.type, "in"))
            following.append(referrer)
        return following


def _reverse(documents: Mapping[str, Document]) -> dict[str, list[tuple[Document, RelatedLink]]]:
    """同じ配信元の関連の先の ID → (関連の元の文書, 関連) の索引を作る。"""
    reverse: dict[str, list[tuple[Document, RelatedLink]]] = {}
    for document in documents.values():
        for link in related_links(document):
            if link.source is None:
                reverse.setdefault(link.to, []).append((document, link))
    return reverse


def walk_related(
    start: Sequence[Document],
    documents: Mapping[str, Document],
    *,
    depth: int,
    direction: Literal["out", "in", "both"],
    resolve_other: Callable[[str, str], Document | None],
) -> tuple[list[tuple[Document, int, str, str, Literal["out", "in"]]], list[str]]:
    """起点から幅優先で `related` をたどり、たどった文書を深さつきで返す。"""
    walk = _Walk(
        documents=documents,
        resolve_other=resolve_other,
        reverse=_reverse(documents),
        visited={document.id for document in start},
    )
    frontier = list(start)
    for level in range(1, depth + 1):
        following: list[Document] = []
        for current in frontier:
            if direction in ("out", "both"):
                following.extend(walk.out(current, level))
            if direction in ("in", "both"):
                following.extend(walk.into(current, level))
        frontier = following
    return walk.found, walk.notes

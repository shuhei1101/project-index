"""`related` のたどり。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from project_index.features.related.types import RelatedLink

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from project_index.features.documents.types import Document


def related_links(document: Document) -> list[RelatedLink]:
    """文書のメタデータの `related` を関連の行の並びにする。"""
    rows = document.metadata.get("related")
    if not isinstance(rows, list):
        return []
    links: list[RelatedLink] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("to"), str):
            continue
        source = row.get("source")
        links.append(
            RelatedLink(
                to=row["to"],
                type=str(row.get("type") or ""),
                source=source if isinstance(source, str) else None,
            )
        )
    return links


def walk_related(  # noqa: C901
    start: Sequence[Document],
    documents: Mapping[str, Document],
    *,
    depth: int,
    direction: Literal["out", "in", "both"],
    resolve_other: Callable[[str, str], Document | None],
) -> tuple[list[tuple[Document, int, str, str, Literal["out", "in"]]], list[str]]:
    """起点から幅優先で `related` をたどり、たどった文書を深さつきで返す。"""
    visited = {document.id for document in start}
    reverse: dict[str, list[tuple[Document, RelatedLink]]] = {}
    for document in documents.values():
        for link in related_links(document):
            if link.source is None:
                reverse.setdefault(link.to, []).append((document, link))
    found: list[tuple[Document, int, str, str, Literal["out", "in"]]] = []
    notes: list[str] = []
    frontier = list(start)
    for level in range(1, depth + 1):
        following: list[Document] = []
        for current in frontier:
            if direction in ("out", "both"):
                for link in related_links(current):
                    if link.source is not None:
                        key = f"{link.source}:{link.to}"
                        target = resolve_other(link.source, link.to)
                        if target is None:
                            note = f"{key} は参照できないので除きました"
                            if note not in notes:
                                notes.append(note)
                            continue
                    else:
                        key = link.to
                        target = documents.get(link.to)
                        if target is None:
                            note = f"{link.to} がありません"
                            if note not in notes:
                                notes.append(note)
                            continue
                    if key in visited:
                        continue
                    visited.add(key)
                    found.append((target, level, current.id, link.type, "out"))
                    following.append(target)
            if direction in ("in", "both"):
                for referrer, link in reverse.get(current.id, []):
                    if referrer.id in visited:
                        continue
                    visited.add(referrer.id)
                    found.append((referrer, level, current.id, link.type, "in"))
                    following.append(referrer)
        frontier = following
    return found, notes

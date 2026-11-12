"""関連の候補の選択。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from project_index.features.related.types import SUGGEST_COUNT, Suggestion

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from project_index.features.documents.types import Document
    from project_index.features.seen.types import Activity

SIGNAL_WEIGHTS = {"co_change": 1.0, "edited": 0.6, "viewed": 0.3}
SCORE_DIGITS = 2

type Signal = Literal["co_change", "edited", "viewed"]


def suggest_related(
    start: Sequence[Document],
    documents: Sequence[Document],
    *,
    exclude: Collection[str],
    co_changed: Mapping[str, int],
    activity: Sequence[Activity],
) -> list[Suggestion]:
    """同じ commit での変更と、この会話の編集・閲覧から関連の候補を選ぶ。"""
    scores: dict[str, float] = {}
    signals: dict[str, list[Signal]] = {}

    def add(doc_id: str, signal: Signal, value: float) -> None:
        scores[doc_id] = scores.get(doc_id, 0.0) + value
        if signal not in signals.setdefault(doc_id, []):
            signals[doc_id].append(signal)

    if co_changed:
        most = max(co_changed.values())
        by_file: dict[str, list[str]] = {}
        for document in documents:
            by_file.setdefault(document.body_path or document.path, []).append(document.id)
        for path, count in co_changed.items():
            for doc_id in by_file.get(path, []):
                add(doc_id, "co_change", SIGNAL_WEIGHTS["co_change"] * count / most)
    for item in activity:
        add(item.doc_id, "edited" if item.kind == "edited" else "viewed", SIGNAL_WEIGHTS[item.kind])
    known = {document.id for document in documents}
    ranked = sorted(
        (doc_id for doc_id in scores if doc_id not in exclude and doc_id in known),
        key=lambda doc_id: (-scores[doc_id], doc_id),
    )
    return [
        Suggestion(id=doc_id, signals=signals[doc_id], score=round(scores[doc_id], SCORE_DIGITS))
        for doc_id in ranked[:SUGGEST_COUNT]
    ]

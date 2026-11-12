from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from project_index.features.documents.types import Document
from project_index.features.related.suggest import suggest_related
from project_index.features.related.types import Suggestion
from project_index.features.seen.types import Activity


def test_suggest_related(make_document: Callable[..., Document]) -> None:
    """信号の和と除く文書（正常系）。"""
    # 準備
    documents = [
        make_document(id=f"doc-{number}", path=f"docs/doc-{number}.yaml") for number in range(1, 6)
    ]
    co_changed = {"docs/doc-4.yaml": 2, "docs/doc-2.yaml": 2}
    activity = [Activity(doc_id="doc-5", kind="viewed", at=datetime(2026, 10, 28, tzinfo=UTC))]
    # 実行
    result = suggest_related(
        [documents[0]],
        documents,
        exclude={"doc-1", "doc-2"},
        co_changed=co_changed,
        activity=activity,
    )
    # 検証
    assert result == [
        Suggestion(id="doc-4", signals=["co_change"], score=1.0),
        Suggestion(id="doc-5", signals=["viewed"], score=0.3),
    ]

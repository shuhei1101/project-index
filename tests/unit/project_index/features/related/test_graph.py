from __future__ import annotations

from collections.abc import Callable

from project_index.features.documents.types import Document
from project_index.features.related.graph import walk_related


def _chain(make_document: Callable[..., Document]) -> dict[str, Document]:
    """文書 1 → 文書 2 → 文書 3 の `related` を持つ文書を返す。"""
    return {
        "doc-1": make_document(
            id="doc-1", metadata={"related": [{"to": "doc-2", "type": "references"}]}
        ),
        "doc-2": make_document(
            id="doc-2", metadata={"related": [{"to": "doc-3", "type": "references"}]}
        ),
        "doc-3": make_document(id="doc-3", metadata={}),
    }


def test_walk_related(make_document: Callable[..., Document]) -> None:
    """深さと向き（正常系）。"""
    # 準備
    documents = _chain(make_document)
    # 実行
    deep, _ = walk_related(
        [documents["doc-1"]],
        documents,
        depth=2,
        direction="out",
        resolve_other=lambda source, doc_id: None,
    )
    shallow, _ = walk_related(
        [documents["doc-1"]],
        documents,
        depth=1,
        direction="out",
        resolve_other=lambda source, doc_id: None,
    )
    # 検証
    assert [(item[0].id, item[1]) for item in deep] == [("doc-2", 1), ("doc-3", 2)]
    assert [(item[0].id, item[1]) for item in shallow] == [("doc-2", 1)]


def test_walk_related_when_cycle(make_document: Callable[..., Document]) -> None:
    """循環（正常系）。"""
    # 準備
    documents = {
        "doc-1": make_document(
            id="doc-1", metadata={"related": [{"to": "doc-2", "type": "references"}]}
        ),
        "doc-2": make_document(
            id="doc-2", metadata={"related": [{"to": "doc-1", "type": "references"}]}
        ),
    }
    # 実行
    items, _ = walk_related(
        [documents["doc-2"]],
        documents,
        depth=4,
        direction="in",
        resolve_other=lambda source, doc_id: None,
    )
    # 検証
    assert [(item[0].id, item[1]) for item in items] == [("doc-1", 1)]


def test_walk_related_when_other_source(make_document: Callable[..., Document]) -> None:
    """読めない別の配信元（正常系）。"""
    # 準備
    start = make_document(
        id="doc-1",
        metadata={"related": [{"to": "x", "type": "references", "source": "other"}]},
    )
    # 実行
    items, notes = walk_related(
        [start],
        {"doc-1": start},
        depth=2,
        direction="out",
        resolve_other=lambda source, doc_id: None,
    )
    # 検証
    assert items == []
    assert any("other:x" in note for note in notes)

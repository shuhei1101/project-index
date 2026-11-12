"""読み取り API の検索。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.read.paths import page_path
from project_index.features.read.types import SearchItem, SearchResult
from project_index.features.search.filters import match_words, normalize
from project_index.features.search.snippets import snippet_lines

if TYPE_CHECKING:
    from collections.abc import Sequence

    from project_index.features.documents.types import Document

SEARCH_QUERY_MAX = 200
SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 100
SNIPPETS_PER_DOC = 3
CONTEXT_LINES = 1


def search_words(documents: Sequence[Document], q: str, limit: int) -> SearchResult:
    """語を全て含む文書と一致した箇所を返す。"""
    words = normalize(q).split()
    matched = sorted(
        (document for document in documents if match_words(document, words)), key=page_path
    )
    items = [
        SearchItem(
            path=page_path(document),
            name=str(document.metadata["name"]),
            snippets=snippet_lines(
                document.body, words, context_lines=CONTEXT_LINES, max_count=SNIPPETS_PER_DOC
            ),
        )
        for document in matched[:limit]
    ]
    return SearchResult(total_count=len(matched), items=items)

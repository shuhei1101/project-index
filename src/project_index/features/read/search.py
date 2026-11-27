"""読み取り API の検索。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.documents.store import page_path
from project_index.features.read.types import SearchItem, SearchResult
from project_index.features.search.filters import match_words, normalize
from project_index.features.search.snippets import count_matches, snippet_lines
from project_index.features.search.types import Condition

if TYPE_CHECKING:
    from collections.abc import Sequence

    from project_index.features.documents.types import Document

SEARCH_QUERY_MAX = 200
SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 100
SNIPPETS_PER_DOC = 3
CONTEXT_LINES = 1


def search_words(
    documents: Sequence[Document],
    q: str,
    limit: int,
    *,
    excluded: Sequence[bool] | None = None,
    include_excluded: bool = False,
) -> SearchResult:
    """語を全て含む文書と一致した箇所を返す。"""
    words = normalize(q).split()
    flags = excluded if excluded is not None else [False] * len(documents)
    found = sorted(
        (
            (document, flag)
            for document, flag in zip(documents, flags, strict=True)
            if match_words(document, words)
        ),
        key=lambda pair: page_path(pair[0]),
    )
    matched = [pair for pair in found if include_excluded or not pair[1]]
    excluded_count = len(found) - len(matched)
    # 一致した行の数は、抜き出しと同じ条件（本文の行がどれかの語を含む）で本文の全ての行を数える
    condition = Condition(field="body", op="contains", values=list(words))
    items = [
        SearchItem(
            path=page_path(document),
            id=document.id,
            file_path=document.path,
            name=str(document.metadata["name"]),
            snippets=snippet_lines(
                document.body, words, context_lines=CONTEXT_LINES, max_count=SNIPPETS_PER_DOC
            ),
            match_count=count_matches(document.body, [condition]),
            excluded=True if flag else None,
        )
        for document, flag in matched[:limit]
    ]
    return SearchResult(
        total_count=len(matched), items=items, excluded_count=excluded_count or None
    )

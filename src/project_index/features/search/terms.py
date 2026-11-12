"""用語の一覧（`list_match_words`）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.access.service import resolve_read_targets
from project_index.features.documents.aliases import collect_aliases, match_words
from project_index.features.search.types import MatchWordsRequest, MatchWordsResult

if TYPE_CHECKING:
    from project_index.features.documents.store import DocumentStore
    from project_index.features.sources.registry import SourceRegistry


def list_match_words(
    request: MatchWordsRequest, *, registry: SourceRegistry, store: DocumentStore
) -> MatchWordsResult:
    """`alias_type` を持つ行の文書から、照合する語を指す文書の ID とともに返す。"""
    target = resolve_read_targets(
        registry=registry, source=request.source, worktree=request.worktree, cwd=request.cwd
    )[0]
    documents = store.load(target).documents
    collection = collect_aliases(target.source, documents)
    return MatchWordsResult(words=match_words(collection.entries))


def render_match_words_markdown(result: MatchWordsResult) -> str:
    """用語の一覧の結果を `| 単語 | 文書 | 種類 |` の表にする。"""
    if not result.words:
        return "用語はありません"
    lines = ["| 単語 | 文書 | 種類 |", "| --- | --- | --- |"]
    lines.extend(f"| {word.word} | {word.id} | {word.kind} |" for word in result.words)
    return "\n".join(lines)

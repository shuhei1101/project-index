"""用語の一覧（`list_match_words`）。"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from project_index.features.access.service import resolve_read_targets
from project_index.features.documents.aliases import collect_aliases, match_words
from project_index.features.search.filters import exclusion_flags
from project_index.features.search.service import excluded_note
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
    # 文書ごとに、文書の行の `search_exclude` に該当するかを求める
    today = datetime.now(UTC).astimezone().date()
    flags = exclusion_flags(target, documents, store=store, today=today)
    excluded = [document for document, flag in zip(documents, flags, strict=True) if flag]
    if request.include_excluded:
        # 除いた文書も返す: 全ての文書から集め、除く文書の単語にマーカーを付ける
        excluded_ids = {document.id for document in excluded}
        words = [
            dataclasses.replace(word, excluded=True) if word.id in excluded_ids else word
            for word in match_words(collect_aliases(target.source, documents).entries)
        ]
        return MatchWordsResult(words=words)
    # 既定: 除く文書を集めずに、除いた用語の文書の数を数える
    kept = [document for document, flag in zip(documents, flags, strict=True) if not flag]
    words = match_words(collect_aliases(target.source, kept).entries)
    excluded_count = sum(1 for document in excluded if "alias_type" in document.metadata)
    return MatchWordsResult(words=words, excluded_count=excluded_count or None)


def render_match_words_markdown(result: MatchWordsResult) -> str:
    """用語の一覧の結果を `| 単語 | 文書 | 種類 |` の表にする（除外の語があれば `除外` の列を加える）。"""
    if not result.words:
        # 単語が無い: 空の通知だけにする
        lines = ["用語はありません"]
    elif any(word.excluded for word in result.words):
        # 除外の単語がある: 末尾に除外の列を加え、該当する行に ✓ を出す
        lines = ["| 単語 | 文書 | 種類 | 除外 |", "| --- | --- | --- | --- |"]
        lines.extend(
            f"| {word.word} | {word.id} | {word.kind} | {'✓' if word.excluded else ''} |"
            for word in result.words
        )
    else:
        # 除外の単語が無い: 3 列の表にする
        lines = ["| 単語 | 文書 | 種類 |", "| --- | --- | --- |"]
        lines.extend(f"| {word.word} | {word.id} | {word.kind} |" for word in result.words)
    # 除いた文書があれば、表の後に除いた件数と取得の仕方を通知する
    if result.excluded_count:
        lines.extend(["", excluded_note(result.excluded_count)])
    return "\n".join(lines)

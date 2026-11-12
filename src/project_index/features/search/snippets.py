"""抜粋の検索と、一致した箇所の抜き出し。"""

from __future__ import annotations

import unicodedata
from bisect import bisect_right
from itertools import accumulate
from typing import TYPE_CHECKING

from project_index.features.search.filters import compile_regex, normalize
from project_index.features.search.types import BodyRange, Condition, Snippet, SnippetLine

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

TEXT_OPS = ("eq", "prefix", "suffix", "contains")


def split_lines(text: str) -> list[str]:
    """本文を行に分ける（行末の `\r` と、改行で終わる本文の最後の空の要素は除く）。"""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    # 本文が改行で終わるときの最後の空の要素は行に数えない
    if text.endswith("\n"):
        lines.pop()
    return lines


def _regex_hits(lines: list[str], condition: Condition) -> set[int]:
    """`regex` の条件に当たった行の番号（0 始まり）を集める。"""
    # 区別しないときは行ごとに NFKC にして、行の対応を保つ
    folded = (
        lines
        if condition.case_sensitive
        else [unicodedata.normalize("NFKC", line) for line in lines]
    )
    whole = "\n".join(folded)
    # 各行の先頭の位置（改行の 1 文字を足す）
    starts = [0, *accumulate(len(line) + 1 for line in folded)][:-1]
    hits: set[int] = set()
    for value in condition.values:
        pattern = compile_regex(value, case_sensitive=condition.case_sensitive)
        for match in pattern.finditer(whole):
            first = bisect_right(starts, match.start()) - 1
            # 改行まで含めて当たっても次の行は当たりにしない
            last = bisect_right(starts, max(match.start(), match.end() - 1)) - 1
            hits.update(range(first, last + 1))
    return hits


def _same(text: str) -> str:
    """文字列をそのまま返す（大文字小文字を区別する比べ方）。"""
    return text


def _text_hits(lines: list[str], condition: Condition) -> set[int]:
    """`eq`・`prefix`・`suffix`・`contains` の条件に値を含む行の番号（0 始まり）を集める。"""
    fold: Callable[[str], str] = _same if condition.case_sensitive else normalize
    wanted = [fold(value) for value in condition.values]
    return {index for index, line in enumerate(lines) if any(word in fold(line) for word in wanted)}


def _hit_lines(lines: list[str], conditions: Sequence[Condition]) -> set[int]:
    """条件のどれかに当たった行の番号（0 始まり）を集める。"""
    hits: set[int] = set()
    for condition in conditions:
        if condition.op == "regex":
            hits |= _regex_hits(lines, condition)
        elif condition.op in TEXT_OPS:
            hits |= _text_hits(lines, condition)
    return hits


def count_matches(text: str, conditions: Sequence[Condition]) -> int:
    """本文のうち、条件のどれかに当たった行の数を返す（同じ行が複数の条件に当たっても 1）。"""
    return len(_hit_lines(split_lines(text), conditions))


def _spans(
    hits: set[int], bounds: list[tuple[int, int]], *, before: int, after: int, last: int
) -> list[list[int]]:
    """当たった行ごとに前後の範囲を、その行を含む範囲の中に切り詰めて作り、重なる範囲は 1 つにまとめる。"""
    spans: list[list[int]] = []
    for index in sorted(hits):
        low, high = next((low, high) for low, high in bounds if low <= index <= high)
        start, end = max(index - before, low), min(index + after, high, last)
        if spans and start <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], end)
        else:
            spans.append([start, end])
    return spans


def find_snippets(
    text: str,
    conditions: Sequence[Condition],
    *,
    before: int,
    after: int,
    max_count: int,
    ranges: Sequence[BodyRange] | None = None,
) -> list[Snippet]:
    """本文から条件に当たる行と前後の行を、行番号つきの抜粋にする。"""
    lines = split_lines(text)
    hits = _hit_lines(lines, conditions)
    # 切り出した範囲の行番号（0 始まり、終わりを含む）。範囲を指さないときは本文の全体
    bounds = (
        [(item.start_line - 1, item.end_line - 1) for item in ranges]
        if ranges is not None
        else [(0, len(lines) - 1)]
    )
    # 範囲の外の当たりは捨てる
    hits = {index for index in hits if any(low <= index <= high for low, high in bounds)}
    spans = _spans(hits, bounds, before=before, after=after, last=len(lines) - 1)
    return [
        Snippet(
            lines=[
                SnippetLine(line=index + 1, text=lines[index], hit=index in hits)
                for index in range(start, end + 1)
            ]
        )
        for start, end in spans[:max_count]
    ]


def snippet_lines(
    text: str, words: Sequence[str], *, context_lines: int, max_count: int
) -> list[str]:
    """本文から語を含む行と前後の行を抜き出す。"""
    condition = Condition(field="body", op="contains", values=list(words))
    snippets = find_snippets(
        text, [condition], before=context_lines, after=context_lines, max_count=max_count
    )
    return ["\n".join(line.text for line in snippet.lines) for snippet in snippets]

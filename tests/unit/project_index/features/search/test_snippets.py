from __future__ import annotations

from project_index.features.search.snippets import count_matches, find_snippets, snippet_lines
from project_index.features.search.types import BodyRange, Condition, Snippet, SnippetLine


def test_find_snippets() -> None:
    """正規表現は行の頭に当たる（正常系）。"""
    # 準備
    text = "\n".join(
        [
            "先頭",
            "説明",
            "## 手順",
            "手順の本文",
            "本文",
            "本文",
            "本文",
            "a ## b",
            "終わり",
            "最後",
        ]
    )
    condition = Condition(field="body", op="regex", values=["^## "])
    # 実行
    result = find_snippets(text, [condition], before=0, after=1, max_count=3)
    # 検証
    assert result == [
        Snippet(
            lines=[
                SnippetLine(line=3, text="## 手順", hit=True),
                SnippetLine(line=4, text="手順の本文", hit=False),
            ]
        )
    ]


def test_find_snippets_when_anchor() -> None:
    """値全体の先頭（正常系）。"""
    # 準備
    text = "alpha\n  beta\ngamma\n  delta\n"
    condition = Condition(field="body", op="regex", values=["\\A\\S"])
    # 実行
    result = find_snippets(text, [condition], before=0, after=0, max_count=3)
    # 検証
    assert result == [Snippet(lines=[SnippetLine(line=1, text="alpha", hit=True)])]


def test_find_snippets_when_overlap() -> None:
    """重なりと上限（正常系）。"""
    # 準備
    text = "\n".join(
        [
            "line1",
            "line2",
            "line3 foo",
            "line4 foo",
            "line5",
            "line6",
            "line7",
            "line8",
            "line9 foo",
            "line10",
        ]
    )
    condition = Condition(field="body", op="contains", values=["ＦＯＯ"])
    # 実行
    result = find_snippets(text, [condition], before=1, after=1, max_count=1)
    # 検証
    assert result == [
        Snippet(
            lines=[
                SnippetLine(line=2, text="line2", hit=False),
                SnippetLine(line=3, text="line3 foo", hit=True),
                SnippetLine(line=4, text="line4 foo", hit=True),
                SnippetLine(line=5, text="line5", hit=False),
            ]
        )
    ]


def test_find_snippets_when_trailing_newline() -> None:
    """末尾の改行と CRLF（正常系）。"""
    # 準備
    text = "a\r\nfoo\r\n"
    condition = Condition(field="body", op="contains", values=["foo"])
    # 実行
    result = find_snippets(text, [condition], before=0, after=5, max_count=3)
    # 検証
    assert result == [Snippet(lines=[SnippetLine(line=2, text="foo", hit=True)])]


def test_find_snippets_when_ranges() -> None:
    """切り出した範囲の中だけ（正常系）。"""
    # 準備
    text = "\n".join(
        [
            "line1",
            "line2 foo",
            "line3",
            "line4",
            "line5",
            "line6",
            "line7 foo",
            "line8",
            "line9",
            "line10",
        ]
    )
    condition = Condition(field="body", op="contains", values=["foo"])
    # 実行
    result = find_snippets(
        text, [condition], before=2, after=2, max_count=3, ranges=[BodyRange(6, 8)]
    )
    # 検証
    assert result == [
        Snippet(
            lines=[
                SnippetLine(line=6, text="line6", hit=False),
                SnippetLine(line=7, text="line7 foo", hit=True),
                SnippetLine(line=8, text="line8", hit=False),
            ]
        )
    ]


def test_count_matches() -> None:
    """行の数と重なり（正常系）。"""
    # 準備
    text = "\n".join(["検索 a", "b", "検索 c", "# 検索の見出し", "e"])
    conditions = [
        Condition(field="body", op="contains", values=["検索"]),
        Condition(field="body", op="regex", values=["^#"]),
    ]
    # 実行
    result = count_matches(text, conditions)
    # 検証
    assert result == 3


def test_count_matches_when_no_conditions() -> None:
    """条件が無い（正常系）。"""
    # 実行
    result = count_matches("検索\n本文", [])
    # 検証
    assert result == 0


def test_snippet_lines() -> None:
    """前後の行と重なり（正常系）。"""
    # 準備
    text = "\n".join(
        [
            "line1",
            "line2",
            "line3 foo",
            "line4 foo",
            "line5",
            "line6",
            "line7",
            "line8",
            "line9",
            "line10",
        ]
    )
    # 実行
    result = snippet_lines(text, ["foo"], context_lines=1, max_count=3)
    # 検証
    assert result == ["line2\nline3 foo\nline4 foo\nline5"]

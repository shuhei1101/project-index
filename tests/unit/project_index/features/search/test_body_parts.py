from __future__ import annotations

from project_index.features.search.body_parts import join_ranges, select_ranges
from project_index.features.search.types import BodyRange, LineRange

SECTIONED_LINES = [
    "# a",
    "",
    "## 経緯",
    "経緯の本文",
    "",
    "## 決まったこと",
    "### 細目",
    "細目の本文",
    "## 残り",
    "残りの本文",
]


def test_select_ranges_when_sections() -> None:
    """節の範囲（正常系）。"""
    # 実行
    result = select_ranges(SECTIONED_LINES, sections=["決まったこと", "細目"], line_range=None)
    # 検証
    assert result == [BodyRange(6, 8)]


def test_select_ranges_when_lines() -> None:
    """行の範囲と末尾（正常系）。"""
    # 実行
    with_limit = select_ranges(
        SECTIONED_LINES, sections=None, line_range=LineRange(offset=3, limit=2)
    )
    to_end = select_ranges(SECTIONED_LINES, sections=None, line_range=LineRange(offset=8))
    beyond = select_ranges(SECTIONED_LINES, sections=None, line_range=LineRange(offset=11))
    # 検証
    assert with_limit == [BodyRange(3, 4)]
    assert to_end == [BodyRange(8, 10)]
    assert beyond == []


def test_select_ranges_when_no_heading() -> None:
    """当たる見出しが無い（正常系）。"""
    # 実行
    result = select_ranges(SECTIONED_LINES, sections=["無い見出し"], line_range=None)
    # 検証
    assert result == []


def test_join_ranges() -> None:
    """複数の範囲（正常系）。"""
    # 実行
    result = join_ranges(["a", "b", "c", "d"], [BodyRange(1, 1), BodyRange(3, 4)])
    # 検証
    assert result == "a\nc\nd"

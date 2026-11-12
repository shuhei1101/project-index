"""本文の一部（sections・lines）の切り出し。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.search.fields import heading_lines
from project_index.features.search.types import BodyRange, LineRange

if TYPE_CHECKING:
    from collections.abc import Sequence


def _section_ranges(lines: Sequence[str], sections: Sequence[str]) -> list[BodyRange]:
    """見出しの文字列が sections のどれかと完全一致するセクションの範囲を集める。"""
    headings = heading_lines(lines)
    ranges: list[BodyRange] = []
    for index, heading in enumerate(headings):
        if heading.text not in sections:
            continue
        # 次の同じか上の階層の見出しの前の行まで（無ければ本文の最後の行まで）
        end = next(
            (
                following.line - 1
                for following in headings[index + 1 :]
                if following.level <= heading.level
            ),
            len(lines),
        )
        ranges.append(BodyRange(heading.line, end))
    return ranges


def _line_range(lines: Sequence[str], line_range: LineRange) -> list[BodyRange]:
    """offset から limit 行（無ければ本文の最後の行）までを、本文の行数で切り詰めた範囲にする。"""
    if line_range.offset > len(lines):
        return []
    end = len(lines) if line_range.limit is None else line_range.offset + line_range.limit - 1
    return [BodyRange(line_range.offset, min(end, len(lines)))]


def select_ranges(
    lines: Sequence[str],
    *,
    sections: Sequence[str] | None,
    line_range: LineRange | None,
) -> list[BodyRange]:
    """sections・lines から、本文の切り出す行の範囲を決める。"""
    found: list[BodyRange] = []
    if sections is not None:
        found.extend(_section_ranges(lines, sections))
    if line_range is not None:
        found.extend(_line_range(lines, line_range))
    # 始まりの行の順に並べ、重なる範囲（親と子のセクションを両方渡したときなど）を 1 つにまとめる
    merged: list[BodyRange] = []
    for item in sorted(found, key=lambda body_range: body_range.start_line):
        if merged and item.start_line <= merged[-1].end_line:
            last = merged[-1]
            merged[-1] = BodyRange(last.start_line, max(last.end_line, item.end_line))
        else:
            merged.append(item)
    return merged


def join_ranges(lines: Sequence[str], ranges: Sequence[BodyRange]) -> str:
    """範囲の行を先頭から改行でつないだ本文を作る（範囲が空なら空文字）。"""
    return "\n".join(line for item in ranges for line in lines[item.start_line - 1 : item.end_line])

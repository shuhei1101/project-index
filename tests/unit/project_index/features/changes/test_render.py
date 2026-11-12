from __future__ import annotations

from datetime import UTC, datetime

from project_index.features.changes.render import render_changes_markdown
from project_index.features.changes.types import (
    ChangeItem,
    ChangesResult,
    ContainsChange,
    RangePoint,
)


def test_render_changes_markdown() -> None:
    """区間と表（正常系）。"""
    # 準備
    result = ChangesResult(
        range_from=RangePoint(
            input="3f2a9c1", commit="3f2a9c1", date=datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
        ),
        range_to=RangePoint(
            input="8b1d4e0", commit="8b1d4e0", date=datetime(2026, 10, 26, 11, 30, tzinfo=UTC)
        ),
        total_count=1,
        items=[
            ChangeItem(
                id="doc-1",
                source=None,
                change="modified",
                keys=["name"],
                values={"name": ("文書 1", "新しい名前")},
            )
        ],
    )
    # 実行
    markdown = render_changes_markdown(result, source_label="sample")
    # 検証
    first_line = markdown.splitlines()[0]
    assert first_line.startswith("sample: 3f2a9c1（")
    assert "→ 8b1d4e0（" in first_line
    assert first_line.endswith("・変わった文書 1 件")
    assert "| doc-1 | modified | name |" in markdown


def test_render_changes_markdown_when_location() -> None:
    """場所を持つ差分を包む（正常系）。"""
    # 準備
    result = ChangesResult(
        range_from=RangePoint(
            input="3f2a9c1", commit="3f2a9c1", date=datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
        ),
        range_to=RangePoint(
            input="8b1d4e0", commit="8b1d4e0", date=datetime(2026, 10, 26, 11, 30, tzinfo=UTC)
        ),
        total_count=2,
        items=[
            ChangeItem(
                id="doc-1",
                source=None,
                change="modified",
                keys=["name"],
                values={"name": ("文書 1", "新しい名前")},
                diff="- name: 文書 1\n+ name: 新しい名前",
                path="/ws/docs/doc-1.yaml",
                scope="section",
            ),
            ChangeItem(
                id="doc-2",
                source=None,
                change="deleted",
                keys=["name"],
                values={"name": ("文書 2", None)},
                diff="- name: 文書 2",
            ),
        ],
    )
    # 実行
    markdown = render_changes_markdown(result, source_label="sample")
    # 検証
    lines = markdown.splitlines()
    opening = '<document path="/ws/docs/doc-1.yaml" scope="section">'
    assert [line for line in lines if line.startswith("<document")] == [opening]
    assert lines.count("</document>") == 1
    assert lines.index("## doc-1") < lines.index(opening)
    assert lines.index(opening) < lines.index("</document>") < lines.index("## doc-2")


def test_render_changes_markdown_when_contains() -> None:
    """語の増減の列（正常系）。"""
    # 準備
    date = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
    result = ChangesResult(
        range_from=RangePoint(input="3f2a9c1", commit="3f2a9c1", date=date),
        range_to=RangePoint(input="8b1d4e0", commit="8b1d4e0", date=date),
        total_count=1,
        items=[
            ChangeItem(
                id="doc-1",
                source=None,
                change="unchanged",
                keys=[],
                values={},
                contains_changes=[
                    ContainsChange(
                        kind="added",
                        from_=RangePoint(input="", commit="1111111", date=date),
                        to=RangePoint(input="", commit="3f2a9c1", date=date),
                        count_before=0,
                        count_after=1,
                    ),
                    ContainsChange(
                        kind="removed",
                        from_=RangePoint(input="", commit="3f2a9c1", date=date),
                        to=RangePoint(input="", commit="8b1d4e0", date=date),
                        count_before=1,
                        count_after=0,
                    ),
                ],
            )
        ],
    )
    # 実行
    markdown = render_changes_markdown(result, source_label="sample")
    # 検証
    assert "単語の増減" in markdown
    assert "| doc-1 | unchanged |  | added 3f2a9c1・removed 8b1d4e0 |" in markdown


def test_render_changes_markdown_when_outside_scope() -> None:
    """作業範囲の外の表示（正常系）。"""
    # 準備
    date = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
    result = ChangesResult(
        range_from=RangePoint(input="3f2a9c1", commit="3f2a9c1", date=date),
        range_to=RangePoint(input="8b1d4e0", commit="8b1d4e0", date=date),
        total_count=0,
        items=[],
        outside_scope=True,
    )
    # 実行
    markdown = render_changes_markdown(result, source_label="other")
    # 検証
    lines = markdown.splitlines()
    assert lines[0] == "作業範囲の外（参考）"
    assert lines[1].startswith("other: 3f2a9c1（")

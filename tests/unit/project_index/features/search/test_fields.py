from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.search.fields import field_values, heading_lines
from project_index.features.search.types import Heading

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.documents.types import Document


def test_field_values(make_document: Callable[..., Document]) -> None:
    """項目の種類ごとの値（正常系）。"""
    # 準備
    document = make_document(
        metadata={"tags": ["a", "b"]},
        data={"owner": {"name": "x"}},
        body="# 見出し",
    )
    # 実行
    tags = field_values(document, "tags")
    owner = field_values(document, "owner.name")
    chars = field_values(document, "@chars")
    missing = field_values(document, "missing")
    # 検証
    assert tags == ["a", "b"]
    assert owner == ["x"]
    assert chars == [5]
    assert missing == []


def test_heading_lines() -> None:
    """階層とコードブロック（正常系）。"""
    # 準備
    lines = ["# a", "", "## b ##", "```", "## c", "```", "### d"]
    # 実行
    result = heading_lines(lines)
    # 検証
    assert result == [
        Heading(line=1, level=1, text="a"),
        Heading(line=3, level=2, text="b"),
        Heading(line=7, level=3, text="d"),
    ]

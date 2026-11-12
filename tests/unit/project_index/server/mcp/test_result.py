from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from mcp.types import TextContent
from pydantic import ValidationError

from project_index.features.access.types import SourceAccess
from project_index.features.changes.types import (
    WORKTREE_LABEL,
    ChangeItem,
    ChangesResult,
    ContainsChange,
    RangePoint,
)
from project_index.features.search.types import (
    SearchItem,
    SearchRequest,
    SearchResult,
    Snippet,
    SnippetLine,
)
from project_index.server.mcp.result import to_tool_result, tool_error
from project_index.shared.errors import SourceNotReadableError


@dataclass
class Sample:
    """結果の dataclass の例。"""

    value: str
    skipped: str | None = None


def _text(content: object) -> str:
    """ツールの結果の text を取り出す。"""
    assert isinstance(content, TextContent)
    return content.text


def test_to_tool_result() -> None:
    """markdown（正常系）。"""
    # 実行
    result = to_tool_result(Sample("x"), "markdown", lambda value: "# x")
    # 検証
    assert _text(result.content[0]) == "# x"
    assert result.structured_content is None


def test_to_tool_result_when_json() -> None:
    """json（正常系）。"""
    # 実行
    result = to_tool_result(Sample("x"), "json", lambda value: "# x")
    # 検証
    assert result.structured_content == {"value": "x"}
    assert json.loads(_text(result.content[0])) == result.structured_content


def test_to_tool_result_when_location() -> None:
    """場所と範囲は項目の直下（正常系）。"""
    # 準備
    items = [
        SearchItem(
            id="src/a",
            source=None,
            values={"path": "a.py", "name": "a"},
            path="/ws/src/a.py",
            scope="full",
        ),
        SearchItem(id="doc-2", source=None, values={"name": "文書 2"}),
    ]
    search = SearchResult(total_count=2, returned=2, view="full", items=items)
    # 実行
    result = to_tool_result(search, "json", None)
    # 検証
    assert result.structured_content is not None
    first, second = result.structured_content["items"]
    assert first["path"] == "/ws/src/a.py"
    assert first["scope"] == "full"
    assert first["values"]["path"] == "a.py"
    assert "path" not in second
    assert "scope" not in second
    assert "path" not in second["values"]


def test_to_tool_result_when_snippet_empty_line() -> None:
    """抜粋の空の行（正常系）。"""
    # 準備
    snippets = [Snippet(lines=[SnippetLine(line=2, text="", hit=False)])]
    items = [SearchItem(id="doc-1", source=None, values={}, snippets=snippets)]
    search = SearchResult(total_count=1, returned=1, view="full", items=items)
    # 実行
    result = to_tool_result(search, "json", None)
    # 検証
    assert result.structured_content is not None
    line = result.structured_content["items"][0]["snippets"][0]["lines"][0]
    assert line == {"line": 2, "text": "", "hit": False}


def test_to_tool_result_when_empty_ranges() -> None:
    """返す行の無い本文の範囲（正常系）。"""
    # 準備
    items = [
        SearchItem(id="doc-1", source=None, values={"body": ""}, ranges=[], total_lines=10),
        SearchItem(id="doc-2", source=None, values={"name": "文書 2"}),
    ]
    search = SearchResult(total_count=2, returned=2, view="full", items=items)
    # 実行
    result = to_tool_result(search, "json", None)
    # 検証
    assert result.structured_content is not None
    first, second = result.structured_content["items"]
    assert first["ranges"] == []
    assert first["total_lines"] == 10
    assert "ranges" not in second
    assert "total_lines" not in second


def test_to_tool_result_when_contains_changes() -> None:
    """語の増減の区間（正常系）。"""
    # 準備
    date = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
    added = ContainsChange(
        kind="added",
        from_=RangePoint(input="", commit="1111111", date=date),
        to=RangePoint(input="", commit="3f2a9c1", date=date),
        count_before=0,
        count_after=1,
    )
    removed = ContainsChange(
        kind="removed",
        from_=RangePoint(input="", commit="3f2a9c1", date=date),
        to=RangePoint(input=WORKTREE_LABEL, commit=None, date=None),
        count_before=1,
        count_after=0,
    )
    changes = ChangesResult(
        range_from=RangePoint(input="1111111", commit="1111111", date=date),
        range_to=RangePoint(input=WORKTREE_LABEL, commit=None, date=None),
        total_count=1,
        items=[
            ChangeItem(
                id="doc-1",
                source=None,
                change="unchanged",
                keys=[],
                values={},
                contains_changes=[added, removed],
            )
        ],
    )
    # 実行
    result = to_tool_result(changes, "json", None)
    # 検証
    assert result.structured_content is not None
    first, second = result.structured_content["items"][0]["contains_changes"]
    assert set(first) == {"kind", "from", "to", "count_before", "count_after"}
    assert set(first["from"]) == {"commit", "date"}
    assert set(first["to"]) == {"commit", "date"}
    assert first["to"]["commit"] == "3f2a9c1"
    assert second["to"] == {"input": WORKTREE_LABEL}


def test_tool_error() -> None:
    """ProjectIndexError（正常系）。"""
    # 準備
    error = SourceNotReadableError(
        message="other は読めません",
        available=[
            SourceAccess(source_id="sample", access="write", current=True, description="サンプル")
        ],
        next_steps=["describe() で使える配信元を見てください"],
    )
    # 実行
    result = tool_error(error)
    # 検証
    text = _text(result.content[0])
    assert result.is_error is True
    assert text.splitlines()[0].startswith("SourceNotReadableError:")
    assert "sample" in text


def test_tool_error_when_validation() -> None:
    """引数の誤り（正常系）。"""
    # 準備
    with pytest.raises(ValidationError) as exc_info:
        SearchRequest(limit="x")  # type: ignore[arg-type]
    # 実行
    result = tool_error(exc_info.value)
    # 検証
    text = _text(result.content[0])
    assert "limit:" in text
    assert "describe" in text


def test_tool_prompt_id() -> None:
    """ツール名をハイフンにする（正常系）。"""
    from project_index.server.mcp.result import tool_prompt_id

    # 準備
    server = "docs"
    # 実行
    result = tool_prompt_id(server, "search_docs")
    # 検証
    assert result == "mcp/docs/tools/search-docs"


def test_mcp_prompt_ids() -> None:
    """instructions と 14 のツール（正常系）。"""
    from project_index.server.mcp.result import mcp_prompt_ids

    # 準備・実行
    result = mcp_prompt_ids()
    # 検証
    assert len(result) == 15
    assert result[0] == "mcp/docs/instructions"
    assert "mcp/admin/tools/check-project" in result

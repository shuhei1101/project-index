from __future__ import annotations

import asyncio
import dataclasses
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent

from project_index.features.search.types import SearchRequest, SearchResult
from project_index.features.settings.types import SourceEntry, TerminalConfig
from project_index.features.sources.registry import SourceRegistry
from project_index.main import build_handlers
from project_index.server.mcp import docs as docs_module
from project_index.server.mcp.docs import build_docs_mcp
from project_index.server.mcp.result import DOCS_INSTRUCTIONS_PROMPT_ID, tool_prompt_id
from project_index.shared.errors import UnknownKindError

TOOL_NAMES = {
    "search_docs",
    "write_docs",
    "delete_docs",
    "describe",
    "list_changes",
    "trace_related",
    "list_match_words",
}


def test_build_docs_mcp(make_mcp_handlers: Callable[..., Any]) -> None:
    """ツールと注釈（正常系）。"""
    # 準備
    mcp = build_docs_mcp(make_mcp_handlers())
    # 実行
    tools = asyncio.run(mcp.list_tools())
    # 検証
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == TOOL_NAMES
    assert by_name["delete_docs"].annotations is not None
    assert by_name["delete_docs"].annotations.destructive_hint is True
    assert by_name["search_docs"].annotations is not None
    assert by_name["search_docs"].annotations.read_only_hint is True
    assert by_name["list_match_words"].annotations is not None
    assert by_name["list_match_words"].annotations.read_only_hint is True


def test_build_docs_mcp_when_instructions(
    make_mcp_handlers: Callable[..., Any], bundled_prompts: Any
) -> None:
    """instructions をプロンプトの YAML から描画する（正常系）。"""
    from mcp import Client

    # 準備
    mcp = build_docs_mcp(make_mcp_handlers())

    async def _initialize() -> str | None:
        async with Client(mcp) as client:
            return client.instructions

    # 実行
    result = asyncio.run(_initialize())
    # 検証
    assert result is not None
    assert result == bundled_prompts.render(DOCS_INSTRUCTIONS_PROMPT_ID)
    assert "grep" in result
    assert "action:" in result
    assert "topic:" in result
    assert "tool:" in result


def test_build_docs_mcp_when_call(
    make_mcp_handlers: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """サービスへの受け渡し（正常系）。"""
    # 準備
    received: list[SearchRequest] = []

    def fake_search_docs(request: SearchRequest, **kwargs: Any) -> SearchResult:
        received.append(request)
        return SearchResult(total_count=0, returned=0, view="summary")

    monkeypatch.setattr(docs_module, "search_docs", fake_search_docs)
    mcp = build_docs_mcp(make_mcp_handlers())
    # 実行
    result = asyncio.run(mcp.call_tool("search_docs", {"source": "sample", "format": "json"}))
    # 検証
    assert isinstance(result, CallToolResult)
    assert received[0].source == "sample"
    assert result.is_error is False
    assert result.structured_content is not None


def test_build_docs_mcp_when_error(
    make_mcp_handlers: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """エラーの変換（正常系）。"""

    # 準備
    def failing_write_docs(*args: Any, **kwargs: Any) -> Any:
        raise UnknownKindError(message="種類がありません", kinds=["rules"])

    monkeypatch.setattr(docs_module, "write_docs", failing_write_docs)
    mcp = build_docs_mcp(make_mcp_handlers())
    arguments = {"operations": [{"op": "create", "kind": "x", "data": {}}]}
    # 実行
    result = asyncio.run(mcp.call_tool("write_docs", arguments))
    # 検証
    assert isinstance(result, CallToolResult)
    assert result.is_error is True
    assert isinstance(result.content[0], TextContent)
    assert "UnknownKindError" in result.content[0].text


def test_build_docs_mcp_when_descriptions(
    make_mcp_handlers: Callable[..., Any], bundled_prompts: Any
) -> None:
    """ツールの説明をプロンプトの YAML から描画する（正常系）。"""
    # 準備
    mcp = build_docs_mcp(make_mcp_handlers())
    # 実行
    tools = asyncio.run(mcp.list_tools())
    # 検証
    by_name = {tool.name: tool for tool in tools}
    assert {name: tool.description for name, tool in by_name.items()} == {
        name: bundled_prompts.render(tool_prompt_id("docs", name)) for name in TOOL_NAMES
    }
    search_description = by_name["search_docs"].description or ""
    for word in (
        "not",
        "glob",
        "@matches",
        "sections",
        "lines",
        "describe(source, kind)",
        "group_by: tags",
    ):
        assert word in search_description
    assert "contains" in (by_name["list_changes"].description or "")
    assert "describe(source, kind)" in (by_name["write_docs"].description or "")
    assert "implements" in (by_name["trace_related"].description or "")
    search_properties = by_name["search_docs"].input_schema["properties"]
    changes_properties = by_name["list_changes"].input_schema["properties"]
    assert "description" in search_properties["sections"]
    assert "description" in search_properties["lines"]
    assert "description" in changes_properties["contains"]


def test_build_docs_mcp_when_loading(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """ツールの呼び出しは読み込みを待ち、スレッドを持たない（正常系）。"""
    # 準備
    config = make_source_dir("sample")
    terminal = make_terminal_config(sources=[make_entry(str(config), source_id="sample")])
    registry = SourceRegistry(loading=True)
    handlers = dataclasses.replace(build_handlers(terminal), registry=registry)
    mcp = build_docs_mcp(handlers)
    observed: dict[str, Any] = {}

    async def scenario() -> list[Any]:
        calls = [
            asyncio.ensure_future(
                mcp.call_tool(
                    "search_docs",
                    {"source": "sample", "format": "json", "cwd": str(config.parent)},
                )
            )
            for _ in range(13)
        ]
        observed["tools"] = await asyncio.wait_for(mcp.list_tools(), timeout=5)
        await asyncio.sleep(0.1)
        observed["done_before"] = [call.done() for call in calls]
        observed["executor_threads"] = [
            thread.name for thread in threading.enumerate() if thread.name.startswith("asyncio_")
        ]
        await asyncio.to_thread(registry.reload, terminal)
        return await asyncio.wait_for(asyncio.gather(*calls), timeout=30)

    # 実行
    results = asyncio.run(scenario())
    # 検証
    assert {tool.name for tool in observed["tools"]} == TOOL_NAMES
    assert observed["done_before"] == [False] * 13
    assert observed["executor_threads"] == []
    assert len(results) == 13
    assert all(isinstance(result, CallToolResult) and not result.is_error for result in results)


def test_wait_target() -> None:
    """要求ごとの待つ行の決め方（正常系）。"""
    # 準備
    from project_index.features.describe.types import DescribeRequest
    from project_index.features.write.types import WriteRequest

    requests = [
        SearchRequest(source="a"),
        SearchRequest(source=["a", "*"]),
        DescribeRequest(outside_scope=True),
        WriteRequest(cwd="/w/a", operations=[]),
        DescribeRequest(),
    ]
    # 実行
    targets = [docs_module._wait_target(request) for request in requests]
    # 検証
    assert targets == [
        {"ids": ["a"]},
        {"every": True},
        {"every": True},
        {"cwd": "/w/a"},
        {},
    ]

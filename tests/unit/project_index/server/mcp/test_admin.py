from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from mcp.types import CallToolResult, TextContent
from project_index.features.admin.types import CheckProjectRequest, CheckProjectResult
from project_index.features.lifecycle.control import RestartControl
from project_index.server.mcp import admin as admin_module
from project_index.server.mcp.admin import build_admin_mcp
from project_index.server.mcp.result import tool_prompt_id

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

TOOL_NAMES = {
    "status",
    "reload",
    "restart",
    "update",
    "check_project",
    "try_convert",
    "write_nav",
}


def test_build_admin_mcp(make_mcp_handlers: Callable[..., Any]) -> None:
    """ツールと注釈（正常系）。"""
    # 準備
    mcp = build_admin_mcp(make_mcp_handlers())
    # 実行
    tools = asyncio.run(mcp.list_tools())
    # 検証
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == TOOL_NAMES
    assert {
        name: by_name[name].annotations.destructive_hint  # type: ignore[union-attr]
        for name in ("restart", "update")
    } == {"restart": True, "update": True}
    assert {
        name: by_name[name].annotations.read_only_hint  # type: ignore[union-attr]
        for name in ("status", "check_project", "try_convert")
    } == {"status": True, "check_project": True, "try_convert": True}
    assert by_name["write_nav"].annotations is not None
    assert by_name["write_nav"].annotations.destructive_hint is False


def test_build_admin_mcp_when_call(
    make_mcp_handlers: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """サービスへの受け渡し（正常系）。"""
    # 準備
    received: list[CheckProjectRequest] = []

    def fake_check_project(request: CheckProjectRequest, **kwargs: Any) -> CheckProjectResult:
        received.append(request)
        return CheckProjectResult(
            path="/tmp/a",
            registered_id=None,
            config_version=None,
            version_state=None,
            violations=[],
            missing_paths=[],
            script_errors=[],
            sync=None,
        )

    monkeypatch.setattr(admin_module, "check_project", fake_check_project)
    mcp = build_admin_mcp(make_mcp_handlers())
    # 実行
    result = asyncio.run(mcp.call_tool("check_project", {"path": "/tmp/a", "format": "json"}))
    # 検証
    assert isinstance(result, CallToolResult)
    assert received[0].path == "/tmp/a"
    assert result.is_error is False
    assert result.structured_content is not None


def test_build_admin_mcp_when_restart_in_progress(make_mcp_handlers: Callable[..., Any]) -> None:
    """再起動の途中をエラーにする（正常系）。"""
    # 準備
    control = RestartControl()
    control.attach(cast("Any", SimpleNamespace(should_exit=False)))
    mcp = build_admin_mcp(make_mcp_handlers(restart=control))
    # 実行
    first = asyncio.run(mcp.call_tool("restart", {}))
    second = asyncio.run(mcp.call_tool("restart", {}))
    # 検証
    assert isinstance(first, CallToolResult)
    assert isinstance(second, CallToolResult)
    assert first.structured_content is not None
    assert first.structured_content["restarting"] is True
    assert second.is_error is True
    assert isinstance(second.content[0], TextContent)
    assert second.content[0].text.startswith("RestartInProgressError")


def test_build_admin_mcp_when_descriptions(
    make_mcp_handlers: Callable[..., Any], bundled_prompts: Any
) -> None:
    """ツールの説明をプロンプトの YAML から描画する（正常系）。"""
    from mcp import Client

    # 準備
    mcp = build_admin_mcp(make_mcp_handlers())

    async def _initialize() -> str | None:
        async with Client(mcp) as client:
            return client.instructions

    # 実行
    tools = asyncio.run(mcp.list_tools())
    instructions = asyncio.run(_initialize())
    # 検証
    assert {tool.name: tool.description for tool in tools} == {
        name: bundled_prompts.render(tool_prompt_id("admin", name)) for name in TOOL_NAMES
    }
    assert instructions is None

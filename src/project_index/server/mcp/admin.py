"""管理の MCP の組み立て。"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, ValidationError

from project_index.features.admin.render import (
    render_check,
    render_reload,
    render_status,
    render_write_nav,
)
from project_index.features.admin.service import (
    check_project,
    get_status,
    reload_config,
    try_convert,
    write_nav,
)
from project_index.features.admin.types import (
    CheckProjectRequest,
    FormatRequest,
    TryConvertRequest,
    WriteNavRequest,
)
from project_index.features.lifecycle.update import update_clone
from project_index.features.settings.query import load_terminal_config
from project_index.server.mcp.result import (
    TOOL_ANNOTATIONS,
    to_tool_result,
    tool_error,
    tool_prompt_id,
)
from project_index.shared.errors import ProjectIndexError

if TYPE_CHECKING:
    from project_index.main import Handlers
    from project_index.shared.runtime import ExecutionSlots

logger = logging.getLogger(__name__)

ADMIN_MCP_NAME = "project-index-admin"

__all__ = [
    "ADMIN_MCP_NAME",
    "build_admin_mcp",
    "check_project",
    "get_status",
    "reload_config",
    "try_convert",
    "update_clone",
    "write_nav",
]


class NoArguments(BaseModel):
    """引数を持たないツールの引数。"""

    model_config = ConfigDict(extra="forbid")


def _signature(model: type[BaseModel]) -> inspect.Signature:
    """要求のモデルのフィールドを、ツールの入力のスキーマにするキーワード引数にする。"""
    parameters = [
        inspect.Parameter(
            name,
            inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty
            if info.is_required()
            else info.get_default(call_default_factory=True),
            annotation=info.annotation,
        )
        for name, info in model.model_fields.items()
    ]
    return inspect.Signature(parameters, return_annotation=CallToolResult)


def _register(
    mcp: MCPServer,
    name: str,
    description: str,
    model: type[BaseModel],
    call: Callable[[Any], Any],
    render: Callable[[Any], str] | None = None,
    *,
    slots: ExecutionSlots,
    wait_loaded: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """要求のモデルを引数に持つツールを 1 つ登録する（`wait_loaded` があれば呼ぶ前に待つ）。"""

    async def tool(**arguments: object) -> CallToolResult:
        try:
            request = model(**arguments)
            if wait_loaded is not None:
                await wait_loaded()
            # 文書の MCP の実行スロットが埋まっていても待たない、管理の MCP の専用の実行スロット
            result = await slots.run_admin(call, request)
            fmt: Literal["markdown", "json"] = getattr(request, "format", "json")
            return to_tool_result(result, fmt, render)
        except (ProjectIndexError, ValidationError) as error:
            return tool_error(error)
        except Exception:
            logger.exception("ツールの処理に失敗した（%s）", name)
            raise

    tool.__signature__ = _signature(model)  # type: ignore[attr-defined]
    tool.__doc__ = description
    mcp.tool(name=name, description=description, annotations=TOOL_ANNOTATIONS[name])(tool)


def build_admin_mcp(handlers: Handlers) -> MCPServer:
    """6 つのツールを持つ管理の MCP を作る。"""
    mcp = MCPServer(ADMIN_MCP_NAME)
    register = functools.partial(_register, slots=handlers.slots)
    register(
        mcp,
        "status",
        handlers.prompts.render(tool_prompt_id("admin", "status")),
        FormatRequest,
        lambda request: get_status(handlers, env=os.environ),
        render_status,
    )
    register(
        mcp,
        "reload",
        handlers.prompts.render(tool_prompt_id("admin", "reload")),
        FormatRequest,
        lambda request: reload_config(handlers),
        render_reload,
        wait_loaded=lambda: handlers.registry.wait_loaded(),
    )
    register(
        mcp,
        "restart",
        handlers.prompts.render(tool_prompt_id("admin", "restart")),
        NoArguments,
        lambda request: handlers.restart.request(),
    )
    register(
        mcp,
        "update",
        handlers.prompts.render(tool_prompt_id("admin", "update")),
        NoArguments,
        lambda request: update_clone(
            handlers.terminal.clone,
            control=handlers.restart,
            # 呼ばれた時点の端末の設定を再読み込みする（違反なら更新せずに伝える）
            mdmark_ref=load_terminal_config(handlers.terminal.file).mdmark_ref,
        ),
        wait_loaded=lambda: handlers.registry.wait_loaded(),
    )
    register(
        mcp,
        "check_project",
        handlers.prompts.render(tool_prompt_id("admin", "check_project")),
        CheckProjectRequest,
        lambda request: check_project(request, handlers=handlers),
        render_check,
        wait_loaded=lambda: handlers.registry.wait_loaded(),
    )
    register(
        mcp,
        "try_convert",
        handlers.prompts.render(tool_prompt_id("admin", "try_convert")),
        TryConvertRequest,
        lambda request: try_convert(request, handlers=handlers),
        wait_loaded=lambda: handlers.registry.wait_loaded(),
    )
    register(
        mcp,
        "write_nav",
        handlers.prompts.render(tool_prompt_id("admin", "write_nav")),
        WriteNavRequest,
        lambda request: write_nav(request, handlers=handlers),
        render_write_nav,
        wait_loaded=lambda: handlers.registry.wait_loaded(),
    )
    return mcp

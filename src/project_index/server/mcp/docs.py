"""文書の MCP の組み立て。"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, DiscoverResult, RequestParams
from pydantic import BaseModel, Field, ValidationError

from project_index.features.access.service import available_sources
from project_index.features.changes.render import render_changes_markdown
from project_index.features.changes.service import list_changes
from project_index.features.changes.types import ChangesRequest
from project_index.features.describe.render import render_describe_markdown
from project_index.features.describe.service import describe
from project_index.features.describe.types import DescribeRequest
from project_index.features.related.render import render_related_markdown
from project_index.features.related.service import trace_related
from project_index.features.related.types import RelatedRequest
from project_index.features.search.render import render_search_markdown
from project_index.features.search.service import search_docs
from project_index.features.search.terms import list_match_words, render_match_words_markdown
from project_index.features.search.types import MatchWordsRequest, SearchRequest
from project_index.features.write.service import delete_docs, write_docs
from project_index.features.write.types import (
    DeleteRequest,
    DeleteResult,
    WriteRequest,
    WriteResult,
)
from project_index.server.mcp.result import (
    DOCS_INSTRUCTIONS_PROMPT_ID,
    TOOL_ANNOTATIONS,
    to_tool_result,
    tool_error,
    tool_prompt_id,
)
from project_index.shared.errors import ProjectIndexError
from project_index.shared.narrowing import is_list

if TYPE_CHECKING:
    from mcp.server.context import ServerRequestContext
    from mcp.server.lowlevel.server import NotificationOptions
    from mcp.server.models import InitializationOptions

    from project_index.main import Handlers

logger = logging.getLogger(__name__)

DOCS_MCP_NAME = "project-index"
# 文書の MCP の instructions 全体の字数の上限
INSTRUCTIONS_MAX_CHARS = 4096

__all__ = [
    "DOCS_MCP_NAME",
    "INSTRUCTIONS_MAX_CHARS",
    "DocsMCPServer",
    "build_docs_mcp",
    "delete_docs",
    "describe",
    "list_changes",
    "list_match_words",
    "search_docs",
    "trace_related",
    "write_docs",
]


def _signature(model: type[BaseModel]) -> inspect.Signature:
    """要求のモデルのフィールドを、ツールの入力のスキーマにするキーワード引数にする。"""
    parameters: list[inspect.Parameter] = []
    for name, info in model.model_fields.items():
        annotation: Any = info.annotation
        extras: dict[str, Any] = {}
        if info.alias:
            # `from` は Python の予約語なので、属性は `from_`・入力のスキーマでは `from` にする
            extras["validation_alias"] = info.alias
        if info.description:
            # 要求のモデルのフィールドの説明を、入力のスキーマの項目の説明に出す
            extras["description"] = info.description
        if extras:
            annotation = Annotated[annotation, Field(**extras)]
        default = (
            inspect.Parameter.empty
            if info.is_required()
            else info.get_default(call_default_factory=True)
        )
        parameters.append(
            inspect.Parameter(
                name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation
            )
        )
    return inspect.Signature(parameters, return_annotation=CallToolResult)


def _register(
    mcp: MCPServer,
    name: str,
    description: str,
    model: type[BaseModel],
    call: Callable[[Any], Any],
    render: Callable[[Any, Any], str] | None,
    *,
    wait_sources: Callable[[BaseModel], Awaitable[None]],
) -> None:
    """要求のモデルを引数に持つツールを 1 つ登録する（呼ぶ前に要求が指す配信元の読み込みを待つ）。"""

    async def tool(**arguments: object) -> CallToolResult:
        try:
            request = model(**arguments)
            await wait_sources(request)
            result = await asyncio.to_thread(call, request)
            fmt: Literal["markdown", "json"] = getattr(request, "format", "json")
            # 描画を持つツール: 要求を添えて Markdown にする
            renderer: Callable[[Any], str] | None = None
            if render is not None:
                bound = render

                def render_with_request(value: object) -> str:
                    return bound(value, request)

                renderer = render_with_request

            return to_tool_result(result, fmt, renderer)
        except (ProjectIndexError, ValidationError) as error:
            return tool_error(error)
        except Exception:
            logger.exception("ツールの処理に失敗した（%s）", name)
            raise

    tool.__signature__ = _signature(model)  # type: ignore[attr-defined]
    tool.__doc__ = description
    mcp.tool(name=name, description=description, annotations=TOOL_ANNOTATIONS[name])(tool)


def _wait_target(request: BaseModel) -> dict[str, Any]:
    """要求のモデルから、待つ配信元の行を決める指す行の待ちの引数を作る。"""
    source: object = getattr(request, "source", None)
    if source == "*" or (is_list(source) and "*" in source):
        return {"every": True}
    if isinstance(source, str):
        return {"ids": [source]}
    if is_list(source):
        return {"ids": list(source)}
    # 作業範囲の外の一覧は、全ての配信元の説明を並べる
    if getattr(request, "outside_scope", False):
        return {"every": True}
    cwd = getattr(request, "worktree", None) or getattr(request, "cwd", None)
    return {"cwd": cwd} if cwd else {}


def _recheck_after[R: (WriteResult, DeleteResult)](
    result: R, cwd: str | None, handlers: Handlers
) -> R:
    """書き込み・削除を当てたとき、作業場所から書ける配信元を裏で検査し直して結果を返す。"""
    if result.applied:
        sources = [
            handlers.registry.get(item.source_id)
            for item in available_sources(cwd, registry=handlers.registry)
            if item.access == "write"
        ]
        handlers.checks.refresh_later(handlers.store, sources)
    return result


class DocsMCPServer(MCPServer):
    """`initialize`・`server/discover` のたびに instructions を描き直す文書の MCP。"""

    def __init__(self, name: str, *, instructions: Callable[[], str]) -> None:
        super().__init__(name, instructions=instructions())
        server = self._lowlevel_server
        create = server.create_initialization_options
        discover = server._handle_discover  # pyright: ignore[reportPrivateUsage]

        # mcp は接続ごとに instructions を作るフックを持たず、どちらの経路も属性を読む
        def create_with_instructions(
            notification_options: NotificationOptions | None = None,
            experimental_capabilities: dict[str, dict[str, Any]] | None = None,
            extensions: dict[str, dict[str, Any]] | None = None,
        ) -> InitializationOptions:
            server.instructions = instructions()
            return create(notification_options, experimental_capabilities, extensions)

        async def discover_with_instructions(
            ctx: ServerRequestContext[Any], params: RequestParams
        ) -> DiscoverResult:
            server.instructions = instructions()
            return await discover(ctx, params)

        setattr(server, "create_initialization_options", create_with_instructions)  # noqa: B010
        server.add_request_handler("server/discover", RequestParams, discover_with_instructions)


def _docs_instructions(handlers: Handlers) -> str:
    """プロンプトの文と配信元と使う場面の一覧を上限の字数に収めて描き、並べた配信元の裏の確認を依頼する。"""
    # initialize の中で Git を呼ばないよう、待たずに今の控えを読む
    guided = [source for source in handlers.registry.served() if source.config.when]
    entries = [{"id": source.id, "when": source.config.when[0]} for source in guided]
    omitted = 0
    text = handlers.prompts.render(
        DOCS_INSTRUCTIONS_PROMPT_ID, {"sources": entries, "omitted": omitted}
    )
    # 上限を超える間は、端末の設定の順の末尾から除く
    while len(text) > INSTRUCTIONS_MAX_CHARS and entries:
        entries.pop()
        omitted += 1
        text = handlers.prompts.render(
            DOCS_INSTRUCTIONS_PROMPT_ID, {"sources": entries, "omitted": omitted}
        )
    handlers.registry.refresh_later([source.id for source in guided])
    return text


def build_docs_mcp(handlers: Handlers) -> MCPServer:
    """7 つのツールを持つ文書の MCP を作る。"""
    mcp = DocsMCPServer(DOCS_MCP_NAME, instructions=functools.partial(_docs_instructions, handlers))
    timeout = handlers.terminal.script_timeout_sec
    register = functools.partial(
        _register,
        wait_sources=lambda request: handlers.registry.wait_for(**_wait_target(request)),
    )

    register(
        mcp,
        "search_docs",
        handlers.prompts.render(tool_prompt_id("docs", "search_docs")),
        SearchRequest,
        lambda request: search_docs(
            request,
            registry=handlers.registry,
            store=handlers.store,
            checker=handlers.checker,
            seen=handlers.seen,
        ),
        lambda result, request: render_search_markdown(result, source_label=result.source_label),
    )
    register(
        mcp,
        "describe",
        handlers.prompts.render(tool_prompt_id("docs", "describe")),
        DescribeRequest,
        lambda request: describe(
            request,
            registry=handlers.registry,
            store=handlers.store,
            terminal=handlers.terminal,
            checks=handlers.checks,
        ),
        lambda result, request: render_describe_markdown(result),
    )
    register(
        mcp,
        "list_changes",
        handlers.prompts.render(tool_prompt_id("docs", "list_changes")),
        ChangesRequest,
        lambda request: list_changes(
            request, registry=handlers.registry, store=handlers.store, seen=handlers.seen
        ),
        lambda result, request: render_changes_markdown(
            result, source_label=str(request.source or "作業中の配信元")
        ),
    )
    register(
        mcp,
        "trace_related",
        handlers.prompts.render(tool_prompt_id("docs", "trace_related")),
        RelatedRequest,
        lambda request: trace_related(
            request, registry=handlers.registry, store=handlers.store, seen=handlers.seen
        ),
        lambda result, request: render_related_markdown(result),
    )
    register(
        mcp,
        "write_docs",
        handlers.prompts.render(tool_prompt_id("docs", "write_docs")),
        WriteRequest,
        lambda request: _recheck_after(
            write_docs(
                request,
                registry=handlers.registry,
                store=handlers.store,
                checker=handlers.checker,
                seen=handlers.seen,
                locks=handlers.locks,
                timeout_sec=timeout,
            ),
            request.cwd,
            handlers,
        ),
        None,
    )
    register(
        mcp,
        "delete_docs",
        handlers.prompts.render(tool_prompt_id("docs", "delete_docs")),
        DeleteRequest,
        lambda request: _recheck_after(
            delete_docs(
                request,
                registry=handlers.registry,
                store=handlers.store,
                checker=handlers.checker,
                locks=handlers.locks,
                timeout_sec=timeout,
            ),
            request.cwd,
            handlers,
        ),
        None,
    )
    register(
        mcp,
        "list_match_words",
        handlers.prompts.render(tool_prompt_id("docs", "list_match_words")),
        MatchWordsRequest,
        lambda request: list_match_words(request, registry=handlers.registry, store=handlers.store),
        lambda result, request: render_match_words_markdown(result),
    )
    return mcp

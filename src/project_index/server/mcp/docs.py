"""文書の MCP の組み立て。"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, DiscoverResult, RequestParams
from pydantic import BaseModel, Field, ValidationError

from project_index.features.access.service import (
    available_sources,
    resolve_read_targets,
    resolve_write_target,
)
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
    DOCS_MCP_SERVER,
    TOOL_ANNOTATIONS,
    to_tool_result,
    tool_error,
    tool_prompt_id,
    tool_unexpected_error,
)
from project_index.shared.deadline import CallLimits, Deadline
from project_index.shared.errors import ProjectIndexError, WorktreeLoadingError
from project_index.shared.narrowing import is_list

if TYPE_CHECKING:
    from pathlib import Path

    from mcp.server.context import ServerRequestContext
    from mcp.server.lowlevel.server import NotificationOptions
    from mcp.server.models import InitializationOptions

    from project_index.features.access.types import Target
    from project_index.main import Handlers
    from project_index.shared.background import BackgroundGate
    from project_index.shared.runtime import ExecutionSlots, RequestRecord

logger = logging.getLogger(__name__)

DOCS_MCP_NAME = "project-index"
# 文書の MCP の instructions 全体の字数の上限
INSTRUCTIONS_MAX_CHARS = 4096
# 要求を受けてから応答を返すまでの上限（秒）。Claude Code の HTTP の要求の待ち時間 60 秒の 8 割
TOOL_RESPONSE_LIMIT_SEC = 48

__all__ = [
    "DOCS_MCP_NAME",
    "INSTRUCTIONS_MAX_CHARS",
    "TOOL_RESPONSE_LIMIT_SEC",
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
    call: Callable[[Any, CallLimits], Any],
    render: Callable[[Any, Any], str] | None,
    *,
    wait_sources: Callable[[BaseModel], Awaitable[None]],
    write_deadline_sec: float,
    gate: BackgroundGate,
    slots: ExecutionSlots,
    prepare: Callable[[BaseModel], Awaitable[None]] | None = None,
) -> None:
    """要求のモデルを引数に持つツールを 1 つ登録する（呼ぶ前に要求が指す配信元の読み込みを待つ）。"""

    async def tool(**arguments: object) -> CallToolResult:
        # 期限は要求を受けた時刻から数える
        started = time.monotonic()
        limits = CallLimits(
            write_deadline=Deadline(limit_sec=write_deadline_sec, started=started),
            respond_by=Deadline(limit_sec=TOOL_RESPONSE_LIMIT_SEC, started=started),
        )
        # ツールの呼び出し 1 回を要求の記録の範囲にし、記録の行を 1 行にする
        with slots.request(name) as record:
            return await _call(record, arguments, limits)

    async def _call(
        record: RequestRecord,
        arguments: dict[str, object],
        limits: CallLimits,
    ) -> CallToolResult:
        try:
            request = model(**arguments)
            record.source = _record_source(request)
            # 読み込みを待つ間も要求の応答中として数え、要求が待っていない行の読み込みを休ませる
            with gate.foreground():
                await wait_sources(request)
            # ワークツリーの初めての読み込みを上限まで待つ（search_docs・write_docs・delete_docs）
            if prepare is not None:
                await prepare(request)
            # サービスの処理の間は要求の応答中として数え、裏の検査と書き出しを休ませる
            with gate.foreground():
                result = await slots.run_docs(call, request, limits)
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
        except Exception as error:
            logger.exception("ツールの処理に失敗した（%s）", name)
            return tool_unexpected_error(error)

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


def _worktree_target(
    request: SearchRequest | WriteRequest | DeleteRequest,
    handlers: Handlers,
    *,
    reload_worktree: bool,
) -> Target | None:
    """要求が指すワークツリーの場所を解く（ワークツリーでなければ `None`）。"""
    if isinstance(request, SearchRequest):
        targets = resolve_read_targets(
            registry=handlers.registry,
            source=request.source,
            worktree=request.worktree,
            cwd=request.cwd,
            outside_scope=request.outside_scope,
            reload_worktree=reload_worktree,
        )
        # 複数の配信元を横断する要求は、ワークツリーを指さない
        if len(targets) != 1:
            return None
        target = targets[0]
    else:
        target = resolve_write_target(
            registry=handlers.registry,
            source=request.source,
            worktree=request.worktree,
            cwd=request.cwd,
            reload_worktree=reload_worktree,
        )
    return target if target.worktree is not None else None


def _load_worktree(
    request: SearchRequest | WriteRequest | DeleteRequest, handlers: Handlers
) -> object:
    """ワークツリーの設定を再読み込みして場所を解き直し、まだ読み込んでいなければ文書を集める。"""
    # 再読み込みは設定が変わっていなければキャッシュで返り、検証に通らなければ例外を伝える
    target = _worktree_target(request, handlers, reload_worktree=True)
    # 解き直した場所がワークツリーでないか、読み込み済みなら集めない
    if target is None or handlers.store.has_worktree(target):
        return None
    return handlers.store.load(target)


async def _load_worktree_recorded(
    request: SearchRequest | WriteRequest | DeleteRequest, handlers: Handlers, source_id: str
) -> object:
    """ワークツリーの読み込みを、呼び出し元と別の要求の記録の範囲で動かす（時間切れの後も 1 行残す）。"""
    with handlers.slots.request("worktree_load", source=source_id):
        return await handlers.slots.run_docs(_load_worktree, request, handlers)


def _record_source(request: BaseModel) -> str | None:
    """要求の記録に残す配信元（1 つの ID を指すときだけ）を返す。"""
    source: object = getattr(request, "source", None)
    return source if isinstance(source, str) else None


async def _ensure_worktree(
    request: SearchRequest | WriteRequest | DeleteRequest,
    handlers: Handlers,
    loads: dict[Path, asyncio.Future[object]],
) -> None:
    """要求が指すワークツリーの初めての読み込みを上限まで待ち、終わらなければ読み込み中のエラーを送る。"""
    if isinstance(request, SearchRequest) and request.ref is not None:
        return
    try:
        # 待つワークツリーを決めるだけなので、ワークツリーの設定は再読み込みしない
        target = await handlers.slots.run_docs(
            functools.partial(_worktree_target, request, handlers, reload_worktree=False)
        )
    except ProjectIndexError:
        # 解けない要求は、サービスが同じ解決で同じエラーを返す
        return
    if target is None:
        return
    root = target.base
    task = loads.get(root)
    # 同じワークツリーの読み込みは 1 つだけ動かし、後の要求は同じ読み込みを待つ
    if task is None or task.done():
        # 設定の再読み込みと文書の読み込みを、待ちの上限の内で待つ 1 つのタスクにする
        task = asyncio.ensure_future(_load_worktree_recorded(request, handlers, target.source.id))
        loads[root] = task

        def forget(done: asyncio.Future[object], root: Path = root) -> None:
            if loads.get(root) is done:
                del loads[root]

        task.add_done_callback(forget)
    wait_sec = handlers.terminal.worktree_load_wait_sec
    try:
        async with asyncio.timeout(wait_sec):
            await asyncio.shield(task)
    except TimeoutError:
        # 読み込みは止めずに続け、次の要求で同じ読み込みの終わりを待つ
        logger.info(
            "ワークツリーを読み込み中のため待たずに返した（%s・%s・%s 秒）",
            target.source.id,
            root,
            wait_sec,
        )
        raise WorktreeLoadingError(
            message=f"{root} を読み込み中です",
            worktree=str(root),
            next_steps=["時間を空けて同じ呼び出しを再実行してください"],
        ) from None


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
    # initialize の中で Git を呼ばないよう、待たずに今のキャッシュを読む
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
        write_deadline_sec=handlers.terminal.write_deadline_sec,
        gate=handlers.gate,
        slots=handlers.slots,
    )
    # ワークツリーのパスごとの読み込み中のタスク（イベントループの中だけで触る）
    loads: dict[Path, asyncio.Future[object]] = {}

    async def ensure_worktree(request: BaseModel) -> None:
        if isinstance(request, SearchRequest | WriteRequest | DeleteRequest):
            await _ensure_worktree(request, handlers, loads)

    register(
        mcp,
        "search_docs",
        handlers.prompts.render(tool_prompt_id(DOCS_MCP_SERVER, "search_docs")),
        SearchRequest,
        lambda request, limits: search_docs(
            request,
            registry=handlers.registry,
            store=handlers.store,
            checker=handlers.checker,
            seen=handlers.seen,
        ),
        lambda result, request: render_search_markdown(result, source_label=result.source_label),
        prepare=ensure_worktree,
    )
    register(
        mcp,
        "describe",
        handlers.prompts.render(tool_prompt_id(DOCS_MCP_SERVER, "describe")),
        DescribeRequest,
        lambda request, limits: describe(
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
        handlers.prompts.render(tool_prompt_id(DOCS_MCP_SERVER, "list_changes")),
        ChangesRequest,
        lambda request, limits: list_changes(
            request, registry=handlers.registry, store=handlers.store, seen=handlers.seen
        ),
        lambda result, request: render_changes_markdown(
            result, source_label=str(request.source or "作業中の配信元")
        ),
    )
    register(
        mcp,
        "trace_related",
        handlers.prompts.render(tool_prompt_id(DOCS_MCP_SERVER, "trace_related")),
        RelatedRequest,
        lambda request, limits: trace_related(
            request, registry=handlers.registry, store=handlers.store, seen=handlers.seen
        ),
        lambda result, request: render_related_markdown(result),
    )
    register(
        mcp,
        "write_docs",
        handlers.prompts.render(tool_prompt_id(DOCS_MCP_SERVER, "write_docs")),
        WriteRequest,
        lambda request, limits: _recheck_after(
            write_docs(
                request,
                registry=handlers.registry,
                store=handlers.store,
                checker=handlers.checker,
                seen=handlers.seen,
                locks=handlers.locks,
                repo_locks=handlers.repo_locks,
                timeout_sec=timeout,
                limits=limits,
            ),
            request.cwd,
            handlers,
        ),
        None,
        prepare=ensure_worktree,
    )
    register(
        mcp,
        "delete_docs",
        handlers.prompts.render(tool_prompt_id(DOCS_MCP_SERVER, "delete_docs")),
        DeleteRequest,
        lambda request, limits: _recheck_after(
            delete_docs(
                request,
                registry=handlers.registry,
                store=handlers.store,
                checker=handlers.checker,
                locks=handlers.locks,
                repo_locks=handlers.repo_locks,
                timeout_sec=timeout,
                limits=limits,
            ),
            request.cwd,
            handlers,
        ),
        None,
        prepare=ensure_worktree,
    )
    register(
        mcp,
        "list_match_words",
        handlers.prompts.render(tool_prompt_id(DOCS_MCP_SERVER, "list_match_words")),
        MatchWordsRequest,
        lambda request, limits: list_match_words(
            request, registry=handlers.registry, store=handlers.store
        ),
        lambda result, request: render_match_words_markdown(result),
    )
    return mcp

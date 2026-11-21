"""アプリの寿命。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager, suppress
from typing import TYPE_CHECKING

from project_index.shared.runtime import record_periodically

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence

    from fastapi import FastAPI
    from mcp.server.mcpserver import MCPServer

    from project_index.features.seen.store import SeenStore
    from project_index.shared.runtime import ExecutionSlots

logger = logging.getLogger(__name__)


def build_lifespan(
    mcps: Sequence[MCPServer], *, seen: SeenStore, slots: ExecutionSlots
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """MCP のセッションの管理と定期の記録を親のアプリの寿命で動かし、起動時に古い会話の記録を削除する。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with AsyncExitStack() as stack:
            # マウントした子のアプリの寿命は動かないので、親で MCP のセッションの管理を動かす
            for mcp in mcps:
                await stack.enter_async_context(mcp.session_manager.run())
            removed = await slots.run_docs(seen.purge_expired)
            logger.info("古い会話の記録を削除した（%s 件）", removed)
            # 実行中・待ち中の数と RSS を、寿命の間ずっと裏で記録する
            recorder = asyncio.create_task(record_periodically(slots))
            try:
                yield
            finally:
                recorder.cancel()
                with suppress(asyncio.CancelledError):
                    await recorder

    return lifespan

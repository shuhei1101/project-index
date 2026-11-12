"""アプリの寿命。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Sequence

    from fastapi import FastAPI
    from mcp.server.mcpserver import MCPServer

    from project_index.features.seen.store import SeenStore

logger = logging.getLogger(__name__)


def build_lifespan(
    mcps: Sequence[MCPServer], *, seen: SeenStore
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """マウントした MCP のセッションの管理を親のアプリの寿命で動かし、起動時に古い会話の記録を削除する。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        async with AsyncExitStack() as stack:
            # マウントした子のアプリの寿命は動かないので、親で MCP のセッションの管理を動かす
            for mcp in mcps:
                await stack.enter_async_context(mcp.session_manager.run())
            removed = await asyncio.to_thread(seen.purge_expired)
            logger.info("古い会話の記録を削除した（%s 件）", removed)
            yield

    return lifespan

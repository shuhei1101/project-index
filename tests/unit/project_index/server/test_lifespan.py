from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING

from fastapi import FastAPI

from project_index.server.lifespan import build_lifespan
from project_index.shared.runtime import ExecutionSlots

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _fake_mcp(name: str, events: list[str]) -> SimpleNamespace:
    """`session_manager.run()` が入った・出たを記録する MCP の偽物を作る。"""

    @asynccontextmanager
    async def run() -> AsyncGenerator[None]:
        events.append(f"{name}.enter")
        yield
        events.append(f"{name}.exit")

    return SimpleNamespace(session_manager=SimpleNamespace(run=run))


def test_build_lifespan() -> None:
    """MCP のセッションの管理を動かす（正常系）。"""
    # 準備
    events: list[str] = []

    def purge_expired() -> int:
        events.append("purge")
        return 0

    seen = SimpleNamespace(purge_expired=purge_expired)
    mcps = [_fake_mcp("docs", events), _fake_mcp("admin", events)]
    lifespan = build_lifespan(mcps, seen=seen, slots=ExecutionSlots())  # type: ignore[arg-type]

    def recording_tasks() -> set[str]:
        return {t.get_coro().__qualname__ for t in asyncio.all_tasks()}  # type: ignore[union-attr]

    async def scenario() -> tuple[list[str], set[str], set[str]]:
        async with lifespan(FastAPI()):
            inside_events = list(events)
            inside_tasks = recording_tasks()
        return inside_events, inside_tasks, recording_tasks()

    # 実行
    inside, tasks_inside, tasks_after = asyncio.run(scenario())
    # 検証
    assert inside.count("docs.enter") == 1
    assert inside.count("admin.enter") == 1
    assert inside.count("purge") == 1
    assert "record_periodically" in tasks_inside
    assert "docs.exit" in events
    assert "admin.exit" in events
    assert "record_periodically" not in tasks_after

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI

from project_index.server.lifespan import build_lifespan


def _fake_mcp(name: str, events: list[str]) -> SimpleNamespace:
    """`session_manager.run()` が入った・出たを記録する MCP の偽物を作る。"""

    @asynccontextmanager
    async def run() -> Any:
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
    lifespan = build_lifespan(mcps, seen=seen)  # type: ignore[arg-type]

    async def scenario() -> list[str]:
        async with lifespan(FastAPI()):
            return list(events)

    # 実行
    inside = asyncio.run(scenario())
    # 検証
    assert inside.count("docs.enter") == 1
    assert inside.count("admin.enter") == 1
    assert inside.count("purge") == 1
    assert "docs.exit" in events
    assert "admin.exit" in events

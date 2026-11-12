from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from project_index.server import app as app_module
from project_index.server.app import build_app, route_operation_id

LOCAL_BASE_URL = "http://127.0.0.1:8786"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "unit-test", "version": "0"},
    },
}


def _endpoint() -> None:
    """ルートの例に使う何もしない関数。"""



async def _noop_receive() -> Message:
    """何も届かない ASGI の receive。"""
    return {"type": "http.request"}


async def _noop_send(message: Message) -> None:
    """何も送らない ASGI の send。"""


def _pass_through(scope: Scope) -> list[Scope]:
    """スラッシュを補うミドルウェアに scope を渡し、次のアプリが受け取った scope を返す。"""
    received: list[Scope] = []

    async def next_app(scope: Scope, receive: Receive, send: Send) -> None:
        received.append(scope)

    middleware = app_module.SlashlessMcpPathMiddleware(next_app, paths=("/mcp", "/_admin/mcp"))
    asyncio.run(middleware(scope, _noop_receive, _noop_send))
    return received


def _handlers(make_mcp_handlers: Callable[..., Any], make_registry: Callable[..., Any]) -> Any:
    """配信元が空の配線済みの関数を作る。"""
    return make_mcp_handlers(registry=make_registry())


def test_build_app(
    make_mcp_handlers: Callable[..., Any], make_registry: Callable[..., Any]
) -> None:
    """入口を全て持つ（正常系）。"""
    # 準備
    app = build_app(_handlers(make_mcp_handlers, make_registry))
    client = TestClient(app)
    # 実行
    sources = client.get("/sources")
    settings = client.get("/settings/sources")
    # 検証
    mounted = [getattr(route, "path", "") for route in app.routes]
    assert sources.status_code == 200
    assert settings.status_code == 200
    assert "/sources/{source}/docs/{path:path}" in mounted
    assert "/openapi.json" not in mounted
    assert "/mcp" in mounted
    assert "/_admin/mcp" in mounted
    session_start = client.post(
        "/_admin/session-start", json={"session_id": "s1", "reason": "startup"}
    )
    assert session_start.status_code == 200
    assert "/_admin/session-context" not in mounted


def test_build_app_when_mcp_without_slash(
    make_mcp_handlers: Callable[..., Any], make_registry: Callable[..., Any]
) -> None:
    """スラッシュ無しの MCP のパスへの POST をリダイレクトせずに MCP が受ける（正常系）。"""
    # 準備
    handlers = make_mcp_handlers(
        registry=make_registry(), seen=SimpleNamespace(purge_expired=lambda: 0)
    )
    app = build_app(handlers)
    with TestClient(app, base_url=LOCAL_BASE_URL, follow_redirects=False) as client:
        # 実行
        docs = client.post("/mcp", headers=MCP_HEADERS, json=INITIALIZE)
        admin = client.post("/_admin/mcp", headers=MCP_HEADERS, json=INITIALIZE)
    # 検証
    assert docs.status_code == 200
    assert "serverInfo" in docs.json()["result"]
    assert admin.status_code == 200
    assert "serverInfo" in admin.json()["result"]


def test_slashless_mcp_path_middleware() -> None:
    """スラッシュ無しの MCP のパスにスラッシュを補う（正常系）。"""
    # 準備
    docs_scope = {"type": "http", "path": "/mcp", "raw_path": b"/mcp"}
    admin_scope = {"type": "http", "path": "/_admin/mcp", "raw_path": b"/_admin/mcp"}
    # 実行
    docs = _pass_through(docs_scope)
    admin = _pass_through(admin_scope)
    # 検証
    assert docs[0]["path"] == "/mcp/"
    assert docs[0]["raw_path"] == b"/mcp/"
    assert admin[0]["path"] == "/_admin/mcp/"
    assert admin[0]["raw_path"] == b"/_admin/mcp/"
    assert docs_scope["path"] == "/mcp"
    assert admin_scope["path"] == "/_admin/mcp"


@pytest.mark.parametrize(
    "scope",
    [
        pytest.param({"type": "http", "path": "/mcp/", "raw_path": b"/mcp/"}, id="with_slash"),
        pytest.param({"type": "http", "path": "/mcpx", "raw_path": b"/mcpx"}, id="prefix"),
        pytest.param(
            {"type": "http", "path": "/sample/mcp", "raw_path": b"/sample/mcp"}, id="nested"
        ),
        pytest.param({"type": "lifespan"}, id="lifespan"),
    ],
)
def test_slashless_mcp_path_middleware_when_other_path(scope: dict[str, Any]) -> None:
    """他のパスと HTTP でない要求はそのまま渡す（正常系）。"""
    # 実行
    received = _pass_through(scope)
    # 検証
    assert received[0] is scope


def test_route_operation_id() -> None:
    """タグと名前を結ぶ（正常系）。"""
    # 準備
    route = APIRoute("/x", _endpoint, tags=["view"], name="get_document")
    # 実行
    result = route_operation_id(route)
    # 検証
    assert result == "view-get_document"


def test_route_operation_id_when_no_tag() -> None:
    """タグが無いと名前だけ（正常系）。"""
    # 準備
    route = APIRoute("/x", _endpoint, tags=[], name="x")
    # 実行
    result = route_operation_id(route)
    # 検証
    assert result == "x"

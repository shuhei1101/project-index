"""読み取り API・端末の設定の API・文書の MCP・管理の MCP・セッションの開始を 1 つのアプリにまとめる。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from project_index.features.read.route import build_read_router
from project_index.features.session_start.route import build_session_start_router
from project_index.features.settings.route import build_settings_router
from project_index.server.error_handlers import register_error_handlers
from project_index.server.lifespan import build_lifespan
from project_index.server.mcp.admin import build_admin_mcp
from project_index.server.mcp.docs import build_docs_mcp

if TYPE_CHECKING:
    from collections.abc import Iterable

    from fastapi.routing import APIRoute
    from starlette.types import ASGIApp, Receive, Scope, Send

    from project_index.main import Handlers

DOCS_MCP_PATH = "/mcp"
ADMIN_MCP_PATH = "/_admin/mcp"


class SlashlessMcpPathMiddleware:
    """スラッシュ無しの MCP のパスへの要求を、ルーティングの前に末尾にスラッシュを付けたパスへ書き換える。"""

    def __init__(self, app: ASGIApp, *, paths: Iterable[str]) -> None:
        self._app = app
        self._paths = frozenset(paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # マウントは `/mcp/...` にだけ当たり、`/mcp` はどのルートにも当たらずリダイレクトになる
        if scope["type"] == "http" and scope["path"] in self._paths:
            scope = {
                **scope,
                "path": scope["path"] + "/",
                "raw_path": scope["raw_path"] + b"/",
            }
        await self._app(scope, receive, send)


def route_operation_id(route: APIRoute) -> str:
    """OpenAPI の operationId をルートのタグと名前から作る（`{タグ}-{名前}`）。"""
    return f"{route.tags[0]}-{route.name}" if route.tags else route.name


def build_app(handlers: Handlers) -> FastAPI:
    """読み取り API・端末の設定の API・文書の MCP・管理の MCP・セッションの開始を 1 つの FastAPI のアプリにまとめる。"""
    docs_mcp = build_docs_mcp(handlers)
    admin_mcp = build_admin_mcp(handlers)
    app = FastAPI(
        lifespan=build_lifespan([docs_mcp, admin_mcp], seen=handlers.seen),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        generate_unique_id_function=route_operation_id,
    )
    app.state.handlers = handlers
    register_error_handlers(app)
    for path, mcp in ((DOCS_MCP_PATH, docs_mcp), (ADMIN_MCP_PATH, admin_mcp)):
        app.mount(
            path,
            mcp.streamable_http_app(
                streamable_http_path="/", stateless_http=True, json_response=True
            ),
        )
    app.add_middleware(SlashlessMcpPathMiddleware, paths=(DOCS_MCP_PATH, ADMIN_MCP_PATH))
    app.include_router(build_read_router(handlers))
    app.include_router(build_settings_router(handlers))
    app.include_router(build_session_start_router(handlers))
    return app

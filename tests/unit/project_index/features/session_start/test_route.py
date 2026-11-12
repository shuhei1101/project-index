from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_index.features.session_start.route import build_session_start_router
from project_index.features.settings.types import SourceEntry, TerminalConfig
from project_index.main import Handlers, build_handlers
from project_index.server.error_handlers import register_error_handlers


def _loaded_handlers(terminal: TerminalConfig) -> Handlers:
    """部品を本物で配線し、配信元を読んだ配線済みの関数を作る。"""
    handlers = build_handlers(terminal)
    handlers.reload_sources(terminal)
    return handlers


def _client(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> tuple[TestClient, Path]:
    """配信元 1 つの配線済みの関数でルーターを載せたクライアントと、配信元のフォルダを返す。"""
    config = make_source_dir("sample")
    handlers = _loaded_handlers(
        make_terminal_config(sources=[make_entry(str(config), source_id="sample")])
    )
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    register_error_handlers(app)
    app.include_router(build_session_start_router(handlers))
    return TestClient(app), config.parent


def test_build_session_start_router(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """本文を検証して記録を削除する（正常系）。"""
    # 準備
    client, _ = _client(make_source_dir, make_terminal_config, make_entry)
    # 実行
    response = client.post("/_admin/session-start", json={"session_id": "s1", "reason": "clear"})
    # 検証
    assert response.status_code == 200
    assert response.json() == {"forgotten": True}


def test_build_session_start_router_when_invalid(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """入力の違反を 422 で返す（異常系）。"""
    # 準備
    client, _ = _client(make_source_dir, make_terminal_config, make_entry)
    # 実行
    response = client.post("/_admin/session-start", json={"session_id": "s1", "reason": "unknown"})
    # 検証
    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert any("reason" in item["path"] for item in body["errors"])


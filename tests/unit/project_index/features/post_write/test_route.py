from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_index.features.post_write.route import build_post_write_router
from project_index.features.seen.types import SessionKey
from project_index.main import build_handlers
from project_index.server.error_handlers import register_error_handlers

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.settings.types import SourceEntry, TerminalConfig
    from project_index.main import Handlers


def _client(handlers: Handlers) -> TestClient:
    """書き込みの後の通知のルーターだけを載せたクライアントを返す。"""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    register_error_handlers(app)
    app.include_router(build_post_write_router(handlers))
    return TestClient(app)


def _handlers(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    *,
    loaded: bool,
) -> tuple[Handlers, Path]:
    """管理用の YAML を持つ配信元 1 つの配線済みの関数と、配信元のフォルダを返す。"""
    config = make_source_dir("sample", unindexed=1)
    terminal = make_terminal_config(sources=[make_entry(str(config), source_id="sample")])
    handlers = build_handlers(terminal)
    # 読み込みを済ませない部品は、配信元の一覧が読み込み中のまま
    if loaded:
        handlers.reload_sources(terminal)
    return handlers, config.parent


def test_build_post_write_router(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """本文を検証して通知を返す（正常系）。"""
    # 準備
    handlers, root = _handlers(make_source_dir, make_terminal_config, make_entry, loaded=True)
    client = _client(handlers)
    # 実行
    response = client.post(
        "/_admin/post-write", json={"session_id": "s1", "paths": [str(root / "src/a.py")]}
    )
    # 検証
    assert response.status_code == 200
    assert len(response.json()["notices"]) == 1


def test_build_post_write_router_when_loading(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """読み込み中は通知しない（正常系）。"""
    # 準備
    handlers, root = _handlers(make_source_dir, make_terminal_config, make_entry, loaded=False)
    client = _client(handlers)
    path = str(root / "src/a.py")
    # 実行
    response = client.post("/_admin/post-write", json={"session_id": "s1", "paths": [path]})
    # 検証
    assert response.status_code == 200
    assert response.json() == {"notices": [], "additional_context": ""}
    assert handlers.notified.take_new(SessionKey("s1", ""), [path]) == [path]


def test_build_post_write_router_when_invalid(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> None:
    """入力の違反を 422 で返す（異常系）。"""
    # 準備
    handlers, _ = _handlers(make_source_dir, make_terminal_config, make_entry, loaded=True)
    client = _client(handlers)
    # 実行
    response = client.post("/_admin/post-write", json={"session_id": "s1", "paths": []})
    # 検証
    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert any("paths" in item["path"] for item in body["errors"])

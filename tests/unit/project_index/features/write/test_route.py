from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_index.features.write import route as route_module
from project_index.features.write.route import build_write_router
from project_index.features.write.types import CommitDocumentsResult, CommitResult
from project_index.main import build_handlers
from project_index.server.error_handlers import register_error_handlers
from project_index.shared.errors import DirectCommitNotPermittedError

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.settings.types import SourceEntry, TerminalConfig
    from project_index.features.write.types import CommitDocumentsRequest
    from project_index.main import Handlers


def _client(handlers: Handlers) -> TestClient:
    """書き込みの API のルーターだけを載せたクライアントを返す。"""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    register_error_handlers(app)
    app.include_router(build_write_router(handlers))
    return TestClient(app)


def _handlers(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
) -> Handlers:
    """配信元 sample 1 つを読み込んだ配線済みの関数を返す。"""
    config = make_source_dir("sample")
    terminal = make_terminal_config(sources=[make_entry(str(config), source_id="sample")])
    handlers = build_handlers(terminal)
    handlers.reload_sources(terminal)
    return handlers


@pytest.fixture
def received(monkeypatch: pytest.MonkeyPatch) -> list[CommitDocumentsRequest]:
    """書き込みと削除の直コミットを、受けた要求を記録して結果を返す偽物にし、記録の並びを返す。"""
    calls: list[CommitDocumentsRequest] = []

    def fake(request: CommitDocumentsRequest, **_parts: Any) -> CommitDocumentsResult:
        calls.append(request)
        return CommitDocumentsResult(
            applied=True,
            writes=[],
            deletes=[],
            commit=CommitResult(sha="0a1b2c3", branch="develop", retried=False),
        )

    monkeypatch.setattr(route_module, "commit_documents", fake)
    return calls


def test_build_write_router(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    received: list[CommitDocumentsRequest],
) -> None:
    """書き込みと削除を 1 回で受けて結果を camelCase で返す（正常系）。"""
    # 準備
    client = _client(_handlers(make_source_dir, make_terminal_config, make_entry))
    body = {
        "writes": [{"op": "create", "kind": "rules", "data": {"id": "doc-9", "name": "文書 9"}}],
        "deletes": [{"id": "doc-1", "expectedVersion": "a1b2c3"}],
        "message": "docs: 更新する",
        "dryRun": True,
    }
    # 実行
    response = client.post("/sources/sample/commits", json=body)
    # 検証
    assert response.status_code == 200
    assert [item.source for item in received] == ["sample"]
    assert [item.dry_run for item in received] == [True]
    assert response.json() == {
        "applied": True,
        "results": [],
        "unlinked": [],
        "commit": {"sha": "0a1b2c3", "branch": "develop", "retried": False},
    }


def test_build_write_router_when_cross_origin(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    received: list[CommitDocumentsRequest],
) -> None:
    """別のオリジンの要求を断る（異常系）。"""
    # 準備
    client = _client(_handlers(make_source_dir, make_terminal_config, make_entry))
    body = {"deletes": [{"id": "doc-1", "expectedVersion": "a1b2c3"}], "message": "docs: 消す"}
    # 実行
    response = client.post(
        "/sources/sample/commits", json=body, headers={"Origin": "http://evil.example"}
    )
    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert received == []


def test_build_write_router_when_empty(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    received: list[CommitDocumentsRequest],
) -> None:
    """書き込みと削除が両方とも空の要求を断る（異常系）。"""
    # 準備
    client = _client(_handlers(make_source_dir, make_terminal_config, make_entry))
    # 実行
    response = client.post("/sources/sample/commits", json={"message": "docs: 何もしない"})
    # 検証
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert received == []


def test_build_write_router_when_service_error(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """サービスの例外をエラーの status にする（異常系）。"""
    # 準備
    def refuse(_request: CommitDocumentsRequest, **_parts: Any) -> CommitDocumentsResult:
        raise DirectCommitNotPermittedError(
            message="書き込みの API から sample の直コミットはできません",
            source_id="sample",
            kinds=["rules"],
        )

    monkeypatch.setattr(route_module, "commit_documents", refuse)
    client = _client(_handlers(make_source_dir, make_terminal_config, make_entry))
    body = {"deletes": [{"id": "doc-1", "expectedVersion": "a1b2c3"}], "message": "docs: 消す"}
    # 実行
    response = client.post("/sources/sample/commits", json=body)
    # 検証
    assert response.status_code == 403
    assert response.json()["kinds"] == ["rules"]

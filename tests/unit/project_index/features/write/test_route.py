from __future__ import annotations

import contextlib
import dataclasses
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_index.features.write import route as route_module
from project_index.features.write.locks import WriteLockKeys
from project_index.features.write.route import build_write_router
from project_index.features.write.source_config import SourceConfigFile
from project_index.features.write.types import CommitDocumentsResult, CommitResult
from project_index.main import build_handlers
from project_index.server.error_handlers import register_error_handlers
from project_index.shared.errors import DirectCommitNotPermittedError, SourceConfigNotPermittedError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from pathlib import Path

    from project_index.features.settings.types import SourceEntry, TerminalConfig
    from project_index.features.sources.types import ServedSource
    from project_index.features.write.types import CommitDocumentsRequest
    from project_index.main import Handlers


def _patch_commit(
    monkeypatch: pytest.MonkeyPatch, fake: Callable[..., CommitDocumentsResult]
) -> None:
    """排他の中の直コミットを偽物にし、直コミットの後処理はその結果をそのまま返す偽物にする。"""

    def locked(request: CommitDocumentsRequest, **parts: Any) -> SimpleNamespace:
        return SimpleNamespace(result=fake(request, **parts))

    def finish(pending: SimpleNamespace, **_parts: Any) -> CommitDocumentsResult:
        return pending.result

    def keys(request: CommitDocumentsRequest, **_parts: Any) -> WriteLockKeys:
        return WriteLockKeys(repo=None, source_id=request.source)

    monkeypatch.setattr(route_module, "write_lock_keys", keys)
    monkeypatch.setattr(route_module, "commit_documents_locked", locked)
    monkeypatch.setattr(route_module, "finish_commit_documents", finish)


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

    _patch_commit(monkeypatch, fake)
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
        "conflict": None,
        "sourceConfig": None,
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

    _patch_commit(monkeypatch, refuse)
    client = _client(_handlers(make_source_dir, make_terminal_config, make_entry))
    body = {"deletes": [{"id": "doc-1", "expectedVersion": "a1b2c3"}], "message": "docs: 消す"}
    # 実行
    response = client.post("/sources/sample/commits", json=body)
    # 検証
    assert response.status_code == 403
    assert response.json()["kinds"] == ["rules"]


def test_build_write_router_when_limits(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """書き込みの API の期限で呼ぶ（正常系）。"""
    # 準備
    limits: list[Any] = []

    def fake(_request: CommitDocumentsRequest, **parts: Any) -> CommitDocumentsResult:
        limits.append(parts["limits"])
        return CommitDocumentsResult(applied=False, writes=[], deletes=[], commit=None)

    _patch_commit(monkeypatch, fake)
    client = _client(_handlers(make_source_dir, make_terminal_config, make_entry))
    body = {
        "writes": [{"op": "create", "kind": "rules", "data": {"id": "doc-9", "name": "文書 9"}}],
        "message": "docs: 更新する",
    }
    # 実行
    response = client.post("/sources/sample/commits", json=body)
    # 検証
    assert response.status_code == 200
    assert limits[0].write_deadline.limit_sec == 20
    assert limits[0].respond_by.limit_sec == 36


def test_build_write_router_when_source_config_file(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配信元の設定の原本を camelCase で返す（正常系）。"""

    # 準備
    def fake(_source: ServedSource) -> SourceConfigFile:
        return SourceConfigFile(
            content="name: sample\n",
            version="a1b2c3",
            branch="develop",
            protected_keys=["validators", "converters", "generators", "direct_commit", "worktrees"],
        )

    monkeypatch.setattr(route_module, "read_source_config_file", fake)
    client = _client(_handlers(make_source_dir, make_terminal_config, make_entry))
    # 実行
    response = client.get("/sources/sample/config/file")
    # 検証
    assert response.status_code == 200
    assert response.json() == {
        "content": "name: sample\n",
        "version": "a1b2c3",
        "branch": "develop",
        "protectedKeys": ["validators", "converters", "generators", "direct_commit", "worktrees"],
    }


def test_build_write_router_when_source_config_not_permitted(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """許可が無ければ 403（異常系）。"""

    # 準備
    def refuse(_source: ServedSource) -> SourceConfigFile:
        raise SourceConfigNotPermittedError(
            message="sample は書き込みの API から配信元の設定を直コミットできません",
            source_id="sample",
            missing=["write_api_config"],
        )

    monkeypatch.setattr(route_module, "read_source_config_file", refuse)
    client = _client(_handlers(make_source_dir, make_terminal_config, make_entry))
    # 実行
    response = client.get("/sources/sample/config/file")
    # 検証
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_build_write_router_when_write_gate(
    make_source_dir: Callable[..., Path],
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """書き込みの関所を通ってから呼ぶ（正常系）。"""
    # 準備
    handlers = _handlers(make_source_dir, make_terminal_config, make_entry)
    events: list[str] = []
    held: list[tuple[WriteLockKeys, float]] = []
    keys = WriteLockKeys(repo=None, source_id="sample")

    class RecordingGates:
        @contextlib.asynccontextmanager
        async def hold(self, given: WriteLockKeys, deadline: Any) -> AsyncGenerator[None]:
            held.append((given, deadline.limit_sec))
            events.append("gate-in")
            yield
            events.append("gate-out")

    def fake_keys(_request: CommitDocumentsRequest, **_parts: Any) -> WriteLockKeys:
        return keys

    def fake_locked(_request: CommitDocumentsRequest, **_parts: Any) -> str:
        events.append("locked")
        return "pending"

    def fake_finish(pending: str, **_parts: Any) -> CommitDocumentsResult:
        events.append(f"finish:{pending}")
        return CommitDocumentsResult(applied=False, writes=[], deletes=[], commit=None)

    monkeypatch.setattr(route_module, "write_lock_keys", fake_keys)
    monkeypatch.setattr(route_module, "commit_documents_locked", fake_locked)
    monkeypatch.setattr(route_module, "finish_commit_documents", fake_finish)
    client = _client(dataclasses.replace(handlers, write_gates=RecordingGates()))
    body = {"deletes": [{"id": "doc-1", "expectedVersion": "a1b2c3"}], "message": "docs: 消す"}
    started = time.monotonic()
    # 実行
    response = client.post("/sources/sample/commits", json=body)
    # 検証
    assert response.status_code == 200
    assert held == [(keys, 20)]
    assert events == ["gate-in", "locked", "gate-out", "finish:pending"]
    assert time.monotonic() - started < 5

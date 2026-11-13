from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_index.features.settings import route as route_module
from project_index.features.settings.query import UNKNOWN_KEY_REASON, load_terminal_config
from project_index.features.settings.route import build_settings_router
from project_index.features.settings.types import SourceAddResult, SourceEntry, TerminalConfig
from project_index.features.sources.registry import SourceRegistry
from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

    from project_index.features.sources.types import SourceStatus

SETTINGS = (
    'version: "1"\n'
    "clone: /tmp/clone\n"
    "sources:\n"
    "  - id: a\n"
    "    config: /tmp/a/project-index.yaml\n"
    "  - id: b\n"
    "    config: /tmp/b/project-index.yaml\n"
)


class FakeRegistry(SourceRegistry):
    """決めた状態を返す配信元の一覧の偽物。"""

    def __init__(self, statuses: list[SourceStatus]) -> None:
        super().__init__()
        self._statuses = statuses

    def statuses(self) -> list[SourceStatus]:
        return self._statuses


def test_build_settings_router_when_get(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_handlers: Callable[..., Any],
    make_terminal_config: Callable[..., TerminalConfig],
    make_status: Callable[..., SourceStatus],
) -> None:
    """行に状態を重ねる（正常系）。"""
    # 準備
    write_files(tmp_path, {"settings.yaml": SETTINGS + "    outside_read: false\n"})
    statuses = [
        make_status("a", 0, config=("/tmp/a/project-index.yaml",)),
        make_status(
            "b",
            1,
            "not_served",
            config=("/tmp/b/project-index.yaml",),
            errors=[Violation(path="documents[0].paths", rule="必須のキーが無い")],
        ),
    ]
    terminal = make_terminal_config(file=tmp_path / "settings.yaml")
    handlers = make_handlers(terminal=terminal, registry=FakeRegistry(statuses))
    app = FastAPI()
    app.include_router(build_settings_router(handlers))
    client = TestClient(app)
    # 実行
    response = client.get("/settings/sources")
    # 検証
    body = response.json()
    assert response.status_code == 200
    assert body["settingsPath"] == str(terminal.file)
    assert [row["id"] for row in body["sources"]] == ["a", "b"]
    assert body["sources"][0]["config"] == ["/tmp/a/project-index.yaml"]
    assert body["sources"][0]["status"] == "serving"
    assert body["sources"][1]["status"] == "not_served"
    assert body["sources"][1]["errors"] == [
        {"path": "documents[0].paths", "reason": "必須のキーが無い"}
    ]
    assert body["sources"][0]["outsideRead"] is True
    assert body["sources"][1]["outsideRead"] is False


def test_build_settings_router_when_pending_reload(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_handlers: Callable[..., Any],
    make_terminal_config: Callable[..., TerminalConfig],
    make_status: Callable[..., SourceStatus],
) -> None:
    """読み直していない行を pending_reload で返す（正常系）。"""
    # 準備
    settings = (
        'version: "1"\n'
        "clone: /tmp/clone\n"
        "sources:\n"
        "  - id: b\n"
        "    config: /tmp/b/project-index.yaml\n"
        "  - id: a\n"
        "    config: /tmp/a/project-index.yaml\n"
        "  - id: fresh\n"
        "    config: /tmp/fresh/project-index.yaml\n"
    )
    write_files(tmp_path, {"settings.yaml": settings})
    statuses = [
        make_status("a", 0, config=("/tmp/a/project-index.yaml",)),
        make_status("b", 1, config=("/tmp/b/project-index.yaml",)),
    ]
    terminal = make_terminal_config(file=tmp_path / "settings.yaml")
    handlers = make_handlers(terminal=terminal, registry=FakeRegistry(statuses))
    app = FastAPI()
    app.include_router(build_settings_router(handlers))
    client = TestClient(app)
    # 実行
    response = client.get("/settings/sources")
    # 検証
    rows = response.json()["sources"]
    assert response.status_code == 200
    assert [(row["id"], row["status"]) for row in rows] == [
        ("b", "serving"),
        ("a", "serving"),
        ("fresh", "pending_reload"),
    ]


def test_build_settings_router_when_put(
    make_handlers: Callable[..., Any],
    make_status: Callable[..., SourceStatus],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """保存して状態を返す（正常系）。"""
    # 準備
    saved: list[list[SourceEntry]] = []

    def fake_save_sources(sources: list[SourceEntry], **kwargs: Any) -> list[SourceStatus]:
        saved.append(list(sources))
        return [make_status("a", 0)]

    monkeypatch.setattr(route_module, "save_sources", fake_save_sources)
    handlers = make_handlers(settings_lock=threading.Lock(), registry=SourceRegistry())
    app = FastAPI()
    app.include_router(build_settings_router(handlers))
    client = TestClient(app)
    body = {"sources": [{"id": "a", "config": ["/tmp/a/project-index.yaml"]}]}
    # 実行
    response = client.put("/settings/sources", json=body, headers={"Sec-Fetch-Site": "same-origin"})
    # 検証
    assert response.status_code == 200
    assert response.json()["sources"][0]["status"] == "serving"
    assert saved[0][0].id == "a"


def test_build_settings_router_when_post(
    make_handlers: Callable[..., Any],
    make_status: Callable[..., SourceStatus],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1 行を追加して 201、同じ id は 409（正常系）。"""
    # 準備
    results = [
        SourceAddResult(result="added", same=None, statuses=[make_status("a", 0)]),
        SourceAddResult(result="exists", same=True, statuses=[]),
    ]

    def fake_add_source(source: SourceEntry, **kwargs: Any) -> SourceAddResult:
        return results.pop(0)

    monkeypatch.setattr(route_module, "add_source", fake_add_source)
    handlers = make_handlers(settings_lock=threading.Lock(), registry=SourceRegistry())
    app = FastAPI()
    app.include_router(build_settings_router(handlers))
    client = TestClient(app)
    body = {"source": {"id": "a", "config": ["/tmp/a/project-index.yaml"]}}
    # 実行
    first = client.post("/settings/sources", json=body)
    second = client.post("/settings/sources", json=body)
    # 検証
    assert first.status_code == 201
    assert first.json()["result"] == "added"
    assert second.status_code == 409
    assert second.json()["result"] == "exists"
    assert second.json()["same"] is True


def test_build_settings_router_when_loading(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_source_dir: Callable[..., Path],
    make_handlers: Callable[..., Any],
) -> None:
    """読み込みが終わるまで待ってから行に状態を重ねる（正常系）。"""
    # 準備
    config = make_source_dir("sample")
    settings = f'version: "1"\nclone: /tmp/clone\nsources:\n  - id: sample\n    config: {config}\n'
    write_files(tmp_path, {"settings.yaml": settings})
    terminal = load_terminal_config(tmp_path / "settings.yaml")
    registry = SourceRegistry(loading=True)
    handlers = make_handlers(terminal=terminal, registry=registry)
    app = FastAPI()
    app.include_router(build_settings_router(handlers))
    observed: dict[str, Any] = {}

    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            request = asyncio.ensure_future(client.get("/settings/sources"))
            await asyncio.sleep(0.1)
            observed["done_before"] = request.done()
            await asyncio.to_thread(registry.reload, terminal)
            return await asyncio.wait_for(request, timeout=10)

    # 実行
    response = asyncio.run(scenario())
    # 検証
    assert observed["done_before"] is False
    assert response.status_code == 200
    assert [(row["id"], row["status"]) for row in response.json()["sources"]] == [
        ("sample", "serving")
    ]


def test_build_settings_router_when_unknown_top_level_key(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_handlers: Callable[..., Any],
    make_terminal_config: Callable[..., TerminalConfig],
    make_status: Callable[..., SourceStatus],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """知らないキーの警告を返す（正常系）。"""
    # 準備
    write_files(tmp_path, {"settings.yaml": "mindstella:\n  threads: 3\n" + SETTINGS})
    statuses = [make_status("a", 0, config=("/tmp/a/project-index.yaml",))]

    def fake_save_sources(sources: list[SourceEntry], **kwargs: Any) -> list[SourceStatus]:
        return statuses

    def fake_add_source(source: SourceEntry, **kwargs: Any) -> SourceAddResult:
        return SourceAddResult(result="added", same=None, statuses=statuses)

    monkeypatch.setattr(route_module, "save_sources", fake_save_sources)
    monkeypatch.setattr(route_module, "add_source", fake_add_source)
    terminal = make_terminal_config(file=tmp_path / "settings.yaml", unknown_keys=["mindstella"])
    handlers = make_handlers(
        terminal=terminal, settings_lock=threading.Lock(), registry=FakeRegistry(statuses)
    )
    app = FastAPI()
    app.include_router(build_settings_router(handlers))
    client = TestClient(app)
    row = {"id": "a", "config": ["/tmp/a/project-index.yaml"]}
    # 実行
    got = client.get("/settings/sources")
    put = client.put("/settings/sources", json={"sources": [row]})
    post = client.post("/settings/sources", json={"source": row})
    # 検証
    expected = [{"path": "mindstella", "reason": UNKNOWN_KEY_REASON}]
    assert got.json()["warnings"] == expected
    assert put.json()["warnings"] == expected
    assert post.json()["warnings"] == expected

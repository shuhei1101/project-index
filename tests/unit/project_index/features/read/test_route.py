from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_index.features.read import route as route_module
from project_index.features.read.route import build_read_router
from project_index.features.sources import registry as registry_module
from project_index.features.sources.registry import SourceRegistry
from project_index.features.sources.types import DocumentTable
from project_index.server.error_handlers import register_error_handlers

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import SimpleNamespace

    from project_index.features.settings.types import SourceEntry, TerminalConfig
    from project_index.features.sources.types import ServedSource, SourceStatus


def _client(handlers: Any) -> TestClient:
    """読み取り API のルーターと例外の変換を載せたアプリのテスト用のクライアントを作る。"""
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(build_read_router(handlers))
    return TestClient(app)


def test_build_read_router(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """8 つのルートが応える（正常系）。"""
    # 準備
    env = make_view_env(
        {
            "schemas/rule.schema.yaml": "type: object\n",
            "docs/a.yaml": "id: a\nname: A\n",
            "tmp/a/.mindstella/docs/D-1.md": "# D-1\n",
        },
        decision_folders=["tmp/a"],
    )
    client = _client(env.handlers)
    # 実行
    responses = {
        path: client.get(path)
        for path in [
            "/sources",
            "/sources/sample/config",
            "/sources/sample/docs",
            "/sources/sample/docs/docs/a.yaml",
            "/sources/sample/decisions",
            "/sources/sample/decisions/D-1",
            "/sources/sample/search?q=A",
            "/sources/sample/refs",
        ]
    }
    # 検証
    assert {path: r.status_code for path, r in responses.items()} == dict.fromkeys(responses, 200)
    assert responses["/sources/sample/docs/docs/a.yaml"].json()["value"] == {"id": "a", "name": "A"}
    assert "updatedAt" in responses["/sources/sample/docs/docs/a.yaml"].json()
    assert responses["/sources/sample/decisions"].json()["decisions"] == [
        {"id": "D-1", "folders": 1}
    ]


def test_build_read_router_when_foreground(
    make_view_env: Callable[..., SimpleNamespace], monkeypatch: pytest.MonkeyPatch
) -> None:
    """サービスの処理の間だけ要求の応答中になる（正常系）。"""
    # 準備
    env = make_view_env()
    seen: list[bool] = []
    original = route_module.list_documents

    def recording_list_documents(*args: Any, **kwargs: Any) -> Any:
        seen.append(env.handlers.gate.active)
        return original(*args, **kwargs)

    monkeypatch.setattr(route_module, "list_documents", recording_list_documents)
    client = _client(env.handlers)
    # 実行
    response = client.get("/sources/sample/docs")
    # 検証
    assert response.status_code == 200
    assert seen == [True]
    assert env.handlers.gate.active is False


def test_build_read_router_when_queries(make_view_env: Callable[..., SimpleNamespace]) -> None:
    """追加したクエリを service に渡す（正常系）。"""
    # 準備
    env = make_view_env(
        {
            "schemas/rule.schema.yaml": "type: object\n",
            "schemas/terms.schema.yaml": "type: object\n",
            "docs/a.yaml": "id: a\nname: A\n",
            "terms.yaml": "terms:\n  - id: term-1\n    name: alpha\n  - id: term-2\n    name: beta\n",
        },
        tables=[
            DocumentTable(
                id="rules", paths=["docs/*.yaml"], schema_path="schemas/rule.schema.yaml"
            ),
            DocumentTable(
                id="terms",
                paths=["terms.yaml"],
                schema_path="schemas/terms.schema.yaml",
                records="terms",
            ),
        ],
        schemas={"rules": {"type": "object"}, "terms": {"type": "object"}},
    )
    client = _client(env.handlers)
    # 実行
    config = client.get("/sources/sample/config?schemas=true").json()
    documents = client.get("/sources/sample/docs?values=true&common_keys=true").json()
    document = client.get("/sources/sample/docs/terms.yaml?id=term-2").json()
    search = client.get("/sources/sample/search?q=beta").json()
    # 検証
    assert config["schemas"] == {"rules": {"type": "object"}, "terms": {}}
    assert config["diff"] == {"ignore_keys": ["updated"]}
    assert documents["documents"][0]["value"] == {"id": "a", "name": "A"}
    assert "version" in documents["documents"][0]
    assert documents["documents"][0]["commonKeys"] == {"id": "a", "name": "A"}
    assert document["metadata"]["id"] == "term-2"
    assert search["items"][0]["id"] == "term-2"
    assert search["items"][0]["filePath"] == "terms.yaml"


@pytest.mark.parametrize(
    ("path", "missing"),
    [
        pytest.param("/sources/unknown/docs", "source", id="source"),
        pytest.param("/sources/sample/docs?ref=no-such", "ref", id="ref"),
        pytest.param("/sources/sample/docs/no/such.yaml", "doc", id="doc"),
    ],
)
def test_build_read_router_when_not_found(
    make_view_env: Callable[..., SimpleNamespace],
    git_repo: Callable[..., Path],
    path: str,
    missing: str,
) -> None:
    """無い配信元・リビジョン・文書を 404 にする（異常系）。"""
    # 準備（リビジョンを解決できる git の配信元）
    root = git_repo({"docs/a.yaml": "id: a\nname: A\n"}, name="sample")
    env = make_view_env(root=root, is_git=True, repo_root=root)
    client = _client(env.handlers)
    # 実行
    response = client.get(path)
    # 検証
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["missing"] == missing


def test_build_read_router_when_include_loading(
    monkeypatch: pytest.MonkeyPatch,
    make_terminal_config: Callable[..., TerminalConfig],
    make_entry: Callable[..., SourceEntry],
    make_served_source: Callable[..., ServedSource],
    make_status: Callable[..., SourceStatus],
    make_handlers: Callable[..., Any],
) -> None:
    """include_loading で読み込みを待たずに返す（正常系）。"""
    # 準備
    entered = threading.Event()
    release = threading.Event()

    def load_source(
        entry: SourceEntry, *, index: int, lookup: object, unit: object = None
    ) -> tuple[Any, Any]:
        del lookup
        entered.set()
        release.wait(timeout=5)
        return make_served_source(id=entry.id), make_status(entry.id, index)

    monkeypatch.setattr(registry_module, "load_source", load_source)
    terminal = make_terminal_config(
        sources=[make_entry("/tmp/slow/project-index.yaml", source_id="slow")]
    )
    registry = SourceRegistry(loading=True)
    worker = threading.Thread(target=registry.load, args=(terminal,))
    worker.start()
    entered.wait(timeout=5)
    client = _client(make_handlers(terminal=terminal, registry=registry))
    # 実行
    response = client.get("/sources?include_loading=true")
    release.set()
    worker.join(timeout=5)
    # 検証
    assert response.status_code == 200
    assert response.json()["sources"] == [
        {"id": "slow", "status": "loading", "errors": [], "configVersion": None}
    ]

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from project_index.features.read.route import build_read_router
from project_index.server.error_handlers import register_error_handlers

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import SimpleNamespace


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


@pytest.mark.parametrize(
    ("path", "missing"),
    [
        pytest.param("/sources/unknown/docs", "source", id="source"),
        pytest.param("/sources/sample/docs?ref=no-such", "ref", id="ref"),
        pytest.param("/sources/sample/docs/no/such.yaml", "doc", id="doc"),
    ],
)
def test_build_read_router_when_not_found(
    make_view_env: Callable[..., SimpleNamespace], path: str, missing: str
) -> None:
    """無い配信元・リビジョン・文書を 404 にする（異常系）。"""
    # 準備
    client = _client(make_view_env().handlers)
    # 実行
    response = client.get(path)
    # 検証
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["missing"] == missing

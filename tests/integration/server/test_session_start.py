from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi.testclient import TestClient

ENDPOINT = "/_admin/session-start"
RETURNED = "この会話で返却済み"


def _post(env: Any, body: dict[str, Any]) -> Any:
    """`POST /_admin/session-start` をフックと同じく Origin なしで呼ぶ。"""
    client: TestClient = env.client
    return client.post(ENDPOINT, json=body)


def test_normal_when_cleared(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """/clear の後は、そのセッションの返却済みの記録を削除する（正常系）。"""
    # 準備
    sample = make_source("sample")
    env = make_server(sample)
    cwd = str(sample.folder)
    first = env.call("search_docs", cwd=cwd, session_id="s1", ids=["doc-1"], view="full")
    again = env.call("search_docs", cwd=cwd, session_id="s1", ids=["doc-1"], view="full")
    # 実行
    response = _post(env, {"session_id": "s1", "reason": "clear"})
    # 検証
    after = env.call("search_docs", cwd=cwd, session_id="s1", ids=["doc-1"], view="full")
    assert response.status_code == 200
    assert response.json() == {"forgotten": True}
    assert RETURNED in again.text
    assert RETURNED not in after.text
    assert after.text == first.text


def test_normal_when_not_forget_reason(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """reason が clear・compact 以外のときは、記録を削除しない（正常系）。"""
    # 準備
    sample = make_source("sample")
    env = make_server(sample)
    cwd = str(sample.folder)
    env.call("search_docs", cwd=cwd, session_id="s1", ids=["doc-1"], view="full")
    # 実行
    response = _post(env, {"session_id": "s1", "reason": "resume"})
    # 検証
    again = env.call("search_docs", cwd=cwd, session_id="s1", ids=["doc-1"], view="full")
    assert response.status_code == 200
    assert response.json() == {"forgotten": False}
    assert RETURNED in again.text


def test_normal_when_loading(
    make_source: Callable[..., Any], make_loading_server: Callable[..., Any]
) -> None:
    """配信元の読み込みを待たずに、記録を削除して答える（正常系）。"""
    # 準備
    loading = make_loading_server(make_source("sample"))
    # 実行
    response = _post(loading.env, {"session_id": "s1", "reason": "compact"})
    # 検証
    assert response.status_code == 200
    assert response.json() == {"forgotten": True}
    assert loading.env.handlers.registry.loading is True


def test_error_when_input_invalid(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """reason が選択肢の外だと 422 を返し、記録を削除しない（異常系）。"""
    # 準備
    sample = make_source("sample")
    env = make_server(sample)
    cwd = str(sample.folder)
    env.call("search_docs", cwd=cwd, session_id="s1", ids=["doc-1"], view="full")
    # 実行
    response = _post(env, {"session_id": "s1", "reason": "restart"})
    # 検証
    again = env.call("search_docs", cwd=cwd, session_id="s1", ids=["doc-1"], view="full")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert any("reason" in item["path"] for item in response.json()["errors"])
    assert RETURNED in again.text

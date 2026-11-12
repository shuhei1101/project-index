from __future__ import annotations

import pytest
from project_index.server.origin import require_same_origin
from project_index.shared.errors import CrossOriginError
from starlette.requests import Request


def _request(headers: dict[str, str]) -> Request:
    """ホストを 127.0.0.1:8786 にした PUT の要求を組み立てる。"""
    all_headers = {"host": "127.0.0.1:8786", **headers}
    scope = {
        "type": "http",
        "method": "PUT",
        "scheme": "http",
        "server": ("127.0.0.1", 8786),
        "path": "/settings/sources",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in all_headers.items()],
    }
    return Request(scope)


def test_require_same_origin() -> None:
    """同じオリジン（正常系）。"""
    # 準備
    request = _request({"origin": "http://127.0.0.1:8786"})
    # 実行・検証
    require_same_origin(request)


def test_require_same_origin_when_fetch_site() -> None:
    """`Origin` が無く `Sec-Fetch-Site` が same-origin（正常系）。"""
    # 準備
    request = _request({"sec-fetch-site": "same-origin"})
    # 実行・検証
    require_same_origin(request)


def test_require_same_origin_when_cross_origin() -> None:
    """別のオリジン（異常系）。"""
    # 準備
    request = _request({"origin": "http://evil.example"})
    # 実行・検証
    with pytest.raises(CrossOriginError) as exc_info:
        require_same_origin(request)
    assert "evil.example" in exc_info.value.message


def test_require_same_origin_when_server_side() -> None:
    """どちらのヘッダーも無い（サーバーの側からの呼び出し・正常系）。"""
    # 準備
    request = _request({})
    # 実行・検証
    require_same_origin(request)


def test_require_same_origin_when_cross_site() -> None:
    """`Origin` が無く `Sec-Fetch-Site` が cross-site（異常系）。"""
    # 準備
    request = _request({"sec-fetch-site": "cross-site"})
    # 実行・検証
    with pytest.raises(CrossOriginError, match="別のオリジン"):
        require_same_origin(request)

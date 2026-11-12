"""端末の設定の API への、ブラウザからの別のオリジンの書き込みの確認。"""

from __future__ import annotations

from fastapi import Request

from project_index.shared.errors import CrossOriginError

SAME_ORIGIN = "same-origin"


def require_same_origin(request: Request) -> None:
    """ブラウザからの要求のうち、project-index と別のオリジンの書き込みを断る。"""
    origin = request.headers.get("origin")
    if origin is not None:
        own = f"{request.url.scheme}://{request.url.netloc}"
        # Origin が project-index のオリジンと違う
        if origin != own:
            raise CrossOriginError(message=f"別のオリジン（{origin}）からの要求は受けません")
        return
    fetch_site = request.headers.get("sec-fetch-site")
    # Origin も Sec-Fetch-Site も無い: サーバーの側からの呼び出しとして受ける
    if fetch_site is None:
        return
    # Origin が無く Sec-Fetch-Site がある: 同じオリジンのときだけ受ける
    if fetch_site != SAME_ORIGIN:
        raise CrossOriginError(message="別のオリジンからの要求は受けません")

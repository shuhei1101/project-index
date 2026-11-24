"""端末の設定の直コミットの許可の登録で、各スクリプトが共有する値と処理。"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

sys.dont_write_bytecode = True

# project-index の端末の設定の API
API = "http://127.0.0.1:8786"
# 直コミットを許可する配信元
TARGET = "project-index"
# 配信元の設定（端末の設定の行の config が指す develop のワークツリーのファイル）
CONFIG = Path("/home/shuhei2441/repo/project-index/.claude/worktrees/develop/project-index.yaml")
# 一時的な通信エラー（再読み込みの間の接続の失敗・5xx）の再試行の回数と間隔
RETRIES = 3
RETRY_INTERVAL_SEC = 2
# 端末の設定の API の 1 回の要求の上限（project-index の再読み込みを待つ）
REQUEST_TIMEOUT_SEC = 60
# 成功の状態コードと、再試行する状態コード（5xx）の下限
HTTP_OK = 200
HTTP_SERVER_ERROR = 500


def request(method: str, path: str, body: object | None = None) -> tuple[int, Any]:
    """端末の設定の API を呼び、状態コードと JSON の本文を返却する。

    再試行するのは読み取り（GET）だけにする。書き換え（PATCH）は、適用された後に応答だけが
    失われると再試行が 409 になり適用済みかを判定できないため、1 回だけ送信する。
    """
    data = None if body is None else json.dumps(body).encode()
    last: Exception | None = None
    attempts = RETRIES if method == "GET" else 1
    for _ in range(attempts):
        # 送信先は固定の http の API（API）だけで、file: などの scheme を受けない
        req = urllib.request.Request(  # noqa: S310
            API + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as res:  # noqa: S310
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as error:
            # 4xx: 再試行せずに状態コードを返却する
            if error.code < HTTP_SERVER_ERROR:
                return error.code, json.loads(error.read() or b"null")
            last = error
        except (urllib.error.URLError, TimeoutError) as error:
            last = error
        time.sleep(RETRY_INTERVAL_SEC)
    message = f"{method} {path}: {last}"
    raise RuntimeError(message)


def allowed_kinds() -> list[str] | None:
    """配信元の設定の `direct_commit.kinds` の種類の ID を返却する。`direct_commit` が無ければ `None`。"""
    import yaml

    config: dict[str, Any] = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    direct: dict[str, Any] | None = config.get("direct_commit")
    if not direct:
        return None
    kinds: list[Any] = direct.get("kinds", [])
    return [_kind_id(kind) for kind in kinds]


def _kind_id(item: object) -> str:
    """種類の要素（文字列か `{id, body}` のオブジェクト）から種類の ID を返却する。"""
    if isinstance(item, str):
        return item
    return str(cast("dict[str, object]", item)["id"])


def api_row(body: dict[str, Any]) -> dict[str, Any] | None:
    """`GET /settings/sources` の本文から対象の配信元の行を返却する。"""
    return next((row for row in body["sources"] if row.get("id") == TARGET), None)


def write_api_kinds(row: dict[str, Any]) -> list[str]:
    """端末の設定の API の行の `directCommit.writeApiKinds` を返却する。"""
    direct: dict[str, Any] = row.get("directCommit") or {}
    kinds: list[str] = direct.get("writeApiKinds") or []
    return list(kinds)

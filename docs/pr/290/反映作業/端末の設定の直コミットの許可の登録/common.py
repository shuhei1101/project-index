"""端末の設定の直コミットの許可の登録で、各スクリプトが共有する値と処理。"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

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


def request(method: str, path: str, body: object | None = None) -> tuple[int, object]:
    """端末の設定の API を呼び、状態コードと JSON の本文を返却する。

    再試行するのは読み取り（GET）だけにする。書き換え（PATCH）は、適用された後に応答だけが
    失われると再試行が 409 になり適用済みかを判定できないため、1 回だけ送信する。
    """
    data = None if body is None else json.dumps(body).encode()
    last: Exception | None = None
    attempts = RETRIES if method == "GET" else 1
    for _ in range(attempts):
        req = urllib.request.Request(
            API + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as res:
                return res.status, json.loads(res.read() or b"null")
        except urllib.error.HTTPError as error:
            # 4xx: 再試行せずに状態コードを返却する
            if error.code < 500:
                return error.code, json.loads(error.read() or b"null")
            last = error
        except (urllib.error.URLError, TimeoutError) as error:
            last = error
        time.sleep(RETRY_INTERVAL_SEC)
    raise RuntimeError(f"{method} {path}: {last}")


def allowed_kinds() -> list[str] | None:
    """配信元の設定の `direct_commit.kinds` の種類の ID を返却する。`direct_commit` が無ければ `None`。"""
    import yaml

    direct = (yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}).get("direct_commit")
    if not direct:
        return None
    # 種類は文字列か `{id, body}` のどちらかで記載されている
    return [kind["id"] if isinstance(kind, dict) else kind for kind in direct.get("kinds", [])]


def api_row(body: dict) -> dict | None:
    """`GET /settings/sources` の本文から対象の配信元の行を返却する。"""
    return next((row for row in body["sources"] if row.get("id") == TARGET), None)


def write_api_kinds(row: dict) -> list[str]:
    """端末の設定の API の行の `directCommit.writeApiKinds` を返却する。"""
    return list((row.get("directCommit") or {}).get("writeApiKinds") or [])

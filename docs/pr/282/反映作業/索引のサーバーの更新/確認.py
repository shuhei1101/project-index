"""稼働中の索引のサーバーの status が、実行中の要求（running）を返すことを確かめる。"""

import json
import sys
import time
import urllib.request
from typing import Any

sys.dont_write_bytecode = True

ADMIN_MCP = "http://127.0.0.1:8786/_admin/mcp/"
# 1 回の打ち切りは status の応答の上限、取り直しは起動し直しの上限 60 秒を 2 秒の間隔で割った回数
TIMEOUT_SEC = 10
INTERVAL_SEC = 2
ATTEMPTS = 30


def call_admin(name: str, arguments: dict[str, object]) -> dict[str, Any]:
    """管理の MCP のツールを 1 回呼び、結果を返す。"""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    request = urllib.request.Request(
        ADMIN_MCP,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
        return json.load(response)["result"]


last = ""
for _ in range(ATTEMPTS):
    try:
        result = call_admin("status", {"format": "json"})
        status: dict[str, Any] = result.get("structuredContent") or {}
        # 起動し直した後の新しいコードは running を返す
        if not result.get("isError") and "running" in status:
            print(
                f"status の running: ok（version: {status['version']}・pid: {status['pid']}・running: {status['running']}）"
            )
            sys.exit(0)
        last = json.dumps(status, ensure_ascii=False)[:500]
    except Exception as error:  # noqa: BLE001
        last = str(error)
    time.sleep(INTERVAL_SEC)
print("status の running: failed")
print(f"POST {ADMIN_MCP} status（format: json）を {ATTEMPTS} 回取り直した最後の応答: {last}")
sys.exit(1)

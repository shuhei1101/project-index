"""マージで develop に入った update の修正を、稼働中の索引のサーバーへ効かせる。

稼働中のプロセスは修正前のコードのため、クローンが既に最新だと update が起動し直さない。
そのときは restart で起動し直す。
"""

import json
import subprocess
import sys
import urllib.request
from typing import Any

sys.dont_write_bytecode = True

ADMIN_MCP = "http://127.0.0.1:8786/_admin/mcp/"
CLONE = "/home/shuhei2441/repo/project-index/.claude/worktrees/develop"
STATUS_TIMEOUT_SEC = 10
# update は git pull・uv sync・migrate --plan・npm install -g を各 300 秒で打ち切るため、その合計 1200 秒に余裕を持たせる
UPDATE_TIMEOUT_SEC = 1260
RESTART_TIMEOUT_SEC = 10
# 受け付ける引数は無し（本番）か --dry-run だけ
MAX_ARGV = 2


def call_admin(name: str, arguments: dict[str, object], timeout: int) -> dict[str, Any]:
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
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.load(response)["result"]


# 前提確認
if len(sys.argv) > MAX_ARGV or (len(sys.argv) == MAX_ARGV and sys.argv[1] != "--dry-run"):
    print("前提確認: failed")
    print(f"受け付けない引数: {sys.argv[1:]}")
    sys.exit(1)
dry_run = len(sys.argv) == MAX_ARGV
try:
    status = call_admin("status", {"format": "json"}, STATUS_TIMEOUT_SEC)["structuredContent"]
    head = subprocess.run(
        ["git", "-C", CLONE, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=60, check=True
    ).stdout.strip()
except Exception as error:  # noqa: BLE001
    print("前提確認: failed")
    print(f"POST {ADMIN_MCP} status / git -C {CLONE} rev-parse HEAD: {error}")
    sys.exit(1)
print("前提確認: ok")

# 計画（--dry-run もここを通る）: 修正を取り込んだコードは status に起動した commit を返す
running = status.get("commit")
print(f"稼働中のバージョン: {status['version']}・pid: {status['pid']}・起動した commit: {running or '（status が返さない）'}")
print(f"クローンの HEAD（{CLONE}）: {head}")
if running == head:
    print("索引のサーバーの更新: skipped")
    sys.exit(0)
print("適用: update を 1 回呼び、restarting: false で移し替えも要らなければ restart を呼ぶ")
if dry_run:
    print("索引のサーバーの更新: changed")
    sys.exit(0)

# 適用: update・restart は冪等でないため再試行しない
try:
    result = call_admin("update", {}, UPDATE_TIMEOUT_SEC)
except Exception as error:  # noqa: BLE001
    print("索引のサーバーの更新: failed")
    print(f"POST {ADMIN_MCP} update: {error}")
    sys.exit(1)
outcome: dict[str, Any] = result.get("structuredContent") or {}
print(json.dumps(outcome, ensure_ascii=False))
if result.get("isError") or outcome.get("migration_needed"):
    print("索引のサーバーの更新: failed")
    print(f"POST {ADMIN_MCP} update")
    print(result.get("content"))
    sys.exit(1)
if outcome.get("restarting"):
    print("索引のサーバーの更新: changed")
    sys.exit(0)
# 取り込む commit が無く、修正前のコードが起動し直さなかった
try:
    restarted = call_admin("restart", {}, RESTART_TIMEOUT_SEC)
except Exception as error:  # noqa: BLE001
    print("索引のサーバーの再起動: failed")
    print(f"POST {ADMIN_MCP} restart: {error}")
    sys.exit(1)
print(json.dumps(restarted.get("structuredContent"), ensure_ascii=False))
if restarted.get("isError"):
    print("索引のサーバーの再起動: failed")
    print(f"POST {ADMIN_MCP} restart")
    print(restarted.get("content"))
    sys.exit(1)
print("索引のサーバーの再起動: changed")

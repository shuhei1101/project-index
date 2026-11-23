"""マージで develop に入った修正を、管理の MCP の update で稼働中の索引のサーバーへ取り込んで起動し直す。"""

import json
import subprocess
import sys
import urllib.request
from typing import Any

sys.dont_write_bytecode = True

ADMIN_MCP = "http://127.0.0.1:8786/_admin/mcp/"
CLONE = "/home/shuhei2441/repo/project-index/.claude/worktrees/develop"
STATUS_TIMEOUT_SEC = 10
# update は git pull・uv sync・migrate --plan を各 300 秒で打ち切るため、その合計に余裕を持たせる
UPDATE_TIMEOUT_SEC = 960
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


def git(*args: str) -> str:
    """クローンで git を実行し、標準出力を返す。"""
    completed = subprocess.run(
        ["git", "-C", CLONE, *args], capture_output=True, text=True, timeout=60, check=True
    )
    return completed.stdout.strip()


# 前提確認
if len(sys.argv) > MAX_ARGV or (len(sys.argv) == MAX_ARGV and sys.argv[1] != "--dry-run"):
    print("前提確認: failed")
    print(f"受け付けない引数: {sys.argv[1:]}")
    sys.exit(1)
dry_run = len(sys.argv) == MAX_ARGV
try:
    status = call_admin("status", {"format": "json"}, STATUS_TIMEOUT_SEC)["structuredContent"]
except Exception as error:  # noqa: BLE001
    print("前提確認: failed")
    print(f"POST {ADMIN_MCP} status: {error}")
    sys.exit(1)
print("前提確認: ok")

# 計画（--dry-run もここを通る）: status が running を返していれば、修正を取り込んだコードで動いている
if "running" in status:
    print("索引のサーバーの更新: skipped")
    sys.exit(0)
try:
    git("fetch", "--quiet", "origin", "develop")
    print(f"取り込む commit（{CLONE}）:")
    print(
        git("log", "--oneline", "HEAD..origin/develop")
        or "（無し。update は新しい commit が無いと起動し直さない）"
    )
except subprocess.CalledProcessError as error:
    print("計画: failed")
    print(" ".join(error.cmd))
    print(error.stderr)
    sys.exit(1)
if dry_run:
    print(f"稼働中のバージョン: {status['version']}・pid: {status['pid']}")
    print("索引のサーバーの更新: changed")
    sys.exit(0)

# 適用: update を 1 回呼ぶ（冪等でないため再試行しない）
try:
    result = call_admin("update", {}, UPDATE_TIMEOUT_SEC)
except Exception as error:  # noqa: BLE001
    print("索引のサーバーの更新: failed")
    print(f"POST {ADMIN_MCP} update: {error}")
    sys.exit(1)
print(json.dumps(result.get("structuredContent"), ensure_ascii=False))
outcome: dict[str, Any] = result.get("structuredContent") or {}
# 取り込んで起動し直し始めたときだけ成功にする
if result.get("isError") or not outcome.get("restarting") or outcome.get("migration_needed"):
    print("索引のサーバーの更新: failed")
    print(f"POST {ADMIN_MCP} update")
    print(result.get("content"))
    sys.exit(1)
print("索引のサーバーの更新: changed")

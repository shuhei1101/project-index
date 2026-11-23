"""稼働中の索引のサーバーの管理の MCP と、クローンの上流へ読み取りだけでつながるかを確かめる。"""

import json
import subprocess
import sys
import urllib.request
from typing import Any

sys.dont_write_bytecode = True

ADMIN_MCP = "http://127.0.0.1:8786/_admin/mcp/"
CLONE = "/home/shuhei2441/repo/project-index/.claude/worktrees/develop"
TIMEOUT_SEC = 10


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


failed = False
# 管理の MCP の status が応答するか
try:
    result = call_admin("status", {"format": "json"})
    if result.get("isError"):
        raise RuntimeError(result["content"])
    print("管理の MCP: ok")
except Exception as error:  # noqa: BLE001
    print("管理の MCP: failed")
    print(f"POST {ADMIN_MCP} status: {error}")
    failed = True

# クローンの上流の develop を読めるか
command = ["git", "-C", CLONE, "ls-remote", "--exit-code", "origin", "refs/heads/develop"]
completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
if completed.returncode == 0:
    print("クローンの上流: ok")
else:
    print("クローンの上流: failed")
    print(" ".join(command))
    print(completed.stderr)
    failed = True

sys.exit(1 if failed else 0)

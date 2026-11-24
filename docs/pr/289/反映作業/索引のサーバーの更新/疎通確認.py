"""索引のサーバーの管理の MCP・クローン・ログに読み取りだけでつながるかを確かめる。"""

import json
import os
import subprocess
import sys
import urllib.request

sys.dont_write_bytecode = True

ADMIN_MCP = "http://127.0.0.1:8786/_admin/mcp/"
CLONE = "/home/shuhei2441/repo/project-index/.claude/worktrees/develop"
SERVER_LOG = "/home/shuhei2441/.local/state/project-index/logs/project-index.log"
STATUS_TIMEOUT_SEC = 10

failed = False
body = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "status", "arguments": {"format": "json"}},
}
request = urllib.request.Request(
    ADMIN_MCP,
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
)
try:
    with urllib.request.urlopen(request, timeout=STATUS_TIMEOUT_SEC) as response:  # noqa: S310
        json.load(response)["result"]["structuredContent"]
    print("管理の MCP の status: ok")
except Exception as error:  # noqa: BLE001
    failed = True
    print("管理の MCP の status: failed")
    print(f"POST {ADMIN_MCP} status: {error}")
try:
    subprocess.run(
        ["git", "-C", CLONE, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    print("クローンの HEAD: ok")
except (OSError, subprocess.SubprocessError) as error:
    failed = True
    print("クローンの HEAD: failed")
    print(f"git -C {CLONE} rev-parse HEAD: {error}")
if os.access(SERVER_LOG, os.R_OK):
    print("索引のサーバーのログ: ok")
else:
    failed = True
    print("索引のサーバーのログ: failed")
    print(f"{SERVER_LOG} を読めない")
sys.exit(1 if failed else 0)

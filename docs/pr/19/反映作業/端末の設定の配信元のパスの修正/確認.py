"""dev-docs が develop の worktree の project-index.yaml で配信元 project-index を配信しているかを観測する。"""

import json
import sys
import urllib.request
from pathlib import Path

SETTINGS = Path("/home/shuhei2441/.config/dev-docs/settings.yaml")
CONFIG = Path("/mnt/c/Users/shuhe/repo/project-index/.claude/worktrees/develop/project-index.yaml")
NEW_LINE = f"    config: {CONFIG}\n"
DOCS_MCP = "http://127.0.0.1:8781/mcp/"
# 作業場所を渡さないと、作業範囲で使える配信元が決まらない
CWD = "/mnt/c/Users/shuhe/repo/project-index"
# dev-docs は配信元が多いと応答が遅いため、PR #3 と同じく待ちを 120 秒取る
TIMEOUT_SEC = 120


def call_tool(name: str, arguments: dict[str, object]) -> str:
    """dev-docs の文書の MCP のツールを呼び、返った本文を返す。"""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    ).encode()
    request = urllib.request.Request(
        DOCS_MCP,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
        result = json.loads(response.read())["result"]
    return "".join(part.get("text", "") for part in result["content"])


def main() -> int:
    """観測した値を出し、効いていなければ 1 を返す。"""
    pointed = NEW_LINE in SETTINGS.read_text(encoding="utf-8")
    print(f"端末の設定の config: {'ok' if pointed else 'failed'}")
    exists = CONFIG.is_file()
    print(f"develop の worktree の project-index.yaml: {'ok' if exists else 'failed'}")
    listed = "| project-index | write |" in call_tool("describe", {"cwd": CWD})
    print(f"describe の一覧の project-index: {'ok' if listed else 'failed'}")
    found = "ARCH-1" in call_tool(
        "search_docs",
        {
            "cwd": CWD,
            "source": "project-index",
            "filter": {"field": "id", "op": "eq", "values": ["ARCH-1"]},
            "view": "ids",
        },
    )
    print(f"search_docs の ARCH-1: {'ok' if found else 'failed'}")
    return 0 if pointed and exists and listed and found else 1


if __name__ == "__main__":
    sys.exit(main())

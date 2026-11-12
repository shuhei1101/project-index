"""端末の設定と project-index のクローンと dev-docs の管理の MCP に、読み取りだけでつながるかを確認する。"""

import json
import sys
import urllib.request
from http import HTTPStatus
from pathlib import Path

SETTINGS = Path("/home/shuhei2441/.config/dev-docs/settings.yaml")
CLONE = Path("/mnt/c/Users/shuhe/repo/project-index")
ADMIN_MCP = "http://127.0.0.1:8781/_admin/mcp/"
# dev-docs は配信元が多いと応答が遅いため、PR #3 と同じく待ちを 120 秒取る
TIMEOUT_SEC = 120


def check_admin_mcp() -> bool:
    """dev-docs の管理の MCP が initialize に応答するかを確認する。"""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "reflection", "version": "0"},
            },
        }
    ).encode()
    request = urllib.request.Request(
        ADMIN_MCP,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:  # noqa: S310
        return response.status == HTTPStatus.OK


def main() -> int:
    """対象ごとに結果の行を出し、failed があれば 1 を返す。"""
    failed = False
    if SETTINGS.is_file() and "id: project-index" in SETTINGS.read_text(encoding="utf-8"):
        print("端末の設定: ok")
    else:
        print("端末の設定: failed")
        print(f"{SETTINGS} に id: project-index の行が無い")
        failed = True
    if (CLONE / ".git").exists():
        print("project-index のクローン: ok")
    else:
        print("project-index のクローン: failed")
        print(f"{CLONE / '.git'} が無い")
        failed = True
    try:
        ok = check_admin_mcp()
        error = ""
    except OSError as exc:
        ok = False
        error = str(exc)
    print(f"dev-docs の管理の MCP: {'ok' if ok else 'failed'}")
    if not ok:
        print(f"POST {ADMIN_MCP} initialize: {error}")
    failed = failed or not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

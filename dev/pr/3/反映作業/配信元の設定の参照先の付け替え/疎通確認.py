"""端末の設定と project-index のクローンと dev-docs の管理の MCP に、読み取りだけでつながるかを確認する。"""

import json
import sys
import urllib.request
from http import HTTPStatus
from pathlib import Path

SETTINGS = Path.home() / ".config/dev-docs/settings.yaml"
CLONE = Path("/mnt/c/Users/shuhe/repo/project-index")
ADMIN_MCP = "http://127.0.0.1:8781/_admin/mcp/"
# dev-docs は配信元が多いと応答が遅いため、待ちを長めに取る
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
    # 端末の設定に project-index の行があるか
    if SETTINGS.is_file() and "id: project-index" in SETTINGS.read_text(encoding="utf-8"):
        print("端末の設定: ok")
    else:
        print("端末の設定: failed")
        failed = True
    # project-index のクローンが git のリポジトリか
    if (CLONE / ".git").exists():
        print("project-index のクローン: ok")
    else:
        print("project-index のクローン: failed")
        failed = True
    # dev-docs の管理の MCP が応答するか
    try:
        ok = check_admin_mcp()
    except OSError:
        ok = False
    print(f"dev-docs の管理の MCP: {'ok' if ok else 'failed'}")
    failed = failed or not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

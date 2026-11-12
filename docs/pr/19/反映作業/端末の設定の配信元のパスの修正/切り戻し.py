"""実行で退避した端末の設定を書き戻し、dev-docs に読み直させる。"""

import json
import shutil
import sys
import urllib.request
from http import HTTPStatus
from pathlib import Path

SETTINGS = Path("/home/shuhei2441/.config/dev-docs/settings.yaml")
BACKUP = Path("/home/shuhei2441/.config/dev-docs/settings.yaml.bak-pr19")
ADMIN_MCP = "http://127.0.0.1:8781/_admin/mcp/"
# PR #3 の実測で読み直しが 10 分を超えたため、同じく 30 分まで待つ
RELOAD_TIMEOUT_SEC = 1800


def call_reload() -> bool:
    """dev-docs の管理の MCP の reload を呼び、応答が返ったかを返す。"""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "reload", "arguments": {}},
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
    with urllib.request.urlopen(request, timeout=RELOAD_TIMEOUT_SEC) as response:  # noqa: S310
        return response.status == HTTPStatus.OK


def main() -> int:
    """退避したファイルがあれば書き戻して読み直させ、失敗したら 1 を返す。"""
    if not BACKUP.is_file():
        print("退避したファイル: failed")
        print(f"{BACKUP} が無い")
        return 1
    shutil.copy2(BACKUP, SETTINGS)
    print("端末の設定の書き戻し: changed")
    try:
        reloaded = call_reload()
    except OSError as exc:
        print("dev-docs の読み直し: failed")
        print(f"POST {ADMIN_MCP} reload: {exc}")
        return 1
    print(f"dev-docs の読み直し: {'changed' if reloaded else 'failed'}")
    return 0 if reloaded else 1


if __name__ == "__main__":
    sys.exit(main())

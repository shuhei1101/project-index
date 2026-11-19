"""PostToolUse のフック。書き込んだファイルのパスを project-index に問い合わせ、返った通知の文面を文脈に追加する。

Usage:
# Claude Code が stdin に PostToolUse の入力の JSON を渡して実行する
python3 post_tool_use.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Any, cast

DEFAULT_PORT = 8786
# `POST /_admin/post-write` を待つ秒数
NOTICE_TIMEOUT_SEC = 3
# 管理用の YAML を自分で扱う文書の MCP と、管理の MCP のツールの名前の接頭辞
SKIPPED_TOOL_PREFIXES = (
    "mcp__plugin_project-index_project-index__",
    "mcp__plugin_project-index_project-index-admin__",
)
# 組み込みのツールごとの、書き込んだパスを持つ `tool_input` のキー
PATH_KEYS = {"Write": "file_path", "Edit": "file_path", "NotebookEdit": "notebook_path"}


def _strings(value: object) -> list[str]:
    """入れ子の辞書・配列をたどり、文字列の値を見つけた順に集める。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in cast("dict[str, Any]", value).values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in cast("list[Any]", value) for text in _strings(item)]
    return []


def collect_paths(tool_name: str, tool_input: dict[str, Any], cwd: str) -> list[str]:
    """ツールの入力から、存在するファイルの絶対パスを重なりを除いて見つけた順に集める。"""
    # 組み込みのツール: パスを持つキーの値だけ
    if tool_name in PATH_KEYS:
        value = tool_input.get(PATH_KEYS[tool_name])
        candidates = [value] if isinstance(value, str) else []
    # MCP のツール: 入力の文字列の値を全て候補にする
    elif tool_name.startswith("mcp__"):
        candidates = _strings(tool_input)
    # それ以外のツール（Bash など）は対象にしない
    else:
        return []
    paths: list[str] = []
    for candidate in candidates:
        # 絶対パスはそのまま、相対パスは作業場所からのパスにする
        path = os.path.normpath(os.path.join(cwd, candidate))
        # パスでない文字列・存在しないパスは捨てる
        if os.path.isfile(path) and path not in paths:
            paths.append(path)
    return paths


def query_notice(event: dict[str, Any], paths: list[str]) -> str | None:
    """`POST /_admin/post-write` に送信し、返った文面を返す（失敗したときは None）。"""
    port = int(os.environ.get("PROJECT_INDEX_PORT") or DEFAULT_PORT)
    payload: dict[str, Any] = {"session_id": event["session_id"], "paths": paths}
    # サブエージェントのときだけ agent_id を送信する
    if event.get("agent_id"):
        payload["agent_id"] = event["agent_id"]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/_admin/post-write",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=NOTICE_TIMEOUT_SEC) as response:  # noqa: S310
            body = json.load(response)
    # 接続できない・打ち切った・200 以外・JSON が読めない: 通知しない
    except (OSError, ValueError) as _error:
        return None
    if not isinstance(body, dict):
        return None
    text = cast("dict[str, Any]", body).get("additional_context")
    return text if isinstance(text, str) else None


def main() -> int:
    """stdin の JSON を読み、書き込んだパスを問い合わせて、返った文面を標準出力に出す。"""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    # 読めない入力では何も出さない
    if not isinstance(event, dict):
        return 0
    event = cast("dict[str, Any]", event)
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict) or not event.get("session_id"):
        return 0
    tool_name = str(event.get("tool_name") or "")
    # 管理用の YAML を自分で扱う文書の MCP・管理の MCP のツールでは問い合わせない
    if tool_name.startswith(SKIPPED_TOOL_PREFIXES):
        return 0
    paths = collect_paths(
        tool_name, cast("dict[str, Any]", tool_input), str(event.get("cwd") or os.getcwd())
    )
    if not paths:
        return 0
    text = query_notice(event, paths)
    if not text:
        return 0
    output = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

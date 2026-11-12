"""PreToolUse のフック。文書の MCP のツールの入力に cwd・session_id・agent_id を入れて返す。

Usage:
# Claude Code が stdin に PreToolUse の入力の JSON を渡して実行する
python3 pre_tool_use.py
"""

from __future__ import annotations

import json
import sys
from typing import Any

# フックの入力から `tool_input` へ上書きで入れるキー
INJECTED_KEYS = ("cwd", "session_id", "agent_id")


def build_updated_input(event: dict[str, Any]) -> dict[str, Any]:
    """`tool_input` のコピーに `INJECTED_KEYS` の値を上書きで入れる。"""
    updated = dict(event["tool_input"])
    for key in INJECTED_KEYS:
        value = event.get(key)
        # 空でない文字列だけを入れる
        if isinstance(value, str) and value:
            updated[key] = value
    # メインのセッション（agent_id が無い）では、エージェントが入れた agent_id を取り除く
    if not event.get("agent_id"):
        updated.pop("agent_id", None)
    return updated


def main() -> int:
    """stdin の JSON を読み、書き換えた入力を標準出力に出す。"""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    # 辞書でない入力と、`tool_input` が辞書でない入力は変えずに戻す
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return 0
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": build_updated_input(event),
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

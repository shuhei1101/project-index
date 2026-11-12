from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

EVENT = {
    "tool_name": "mcp__plugin_project-index_project-index__search_docs",
    "tool_input": {"query": "起動", "cwd": "/other", "note": "そのまま"},
    "session_id": "s1",
    "cwd": "/repo/sample",
    "agent_id": "a1",
}


def test_normal(run_hook: Callable[..., Any]) -> None:
    """`tool_input` に作業場所とセッションを入れて `updatedInput` で返す（正常系）。"""
    # 実行
    result = run_hook("pre_tool_use", EVENT, {})
    # 検証
    specific = result.output["hookSpecificOutput"]
    assert result.code == 0
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["updatedInput"] == {
        "query": "起動",
        "cwd": "/repo/sample",
        "note": "そのまま",
        "session_id": "s1",
        "agent_id": "a1",
    }
    assert specific["permissionDecision"] == "allow"
    assert specific["permissionDecisionReason"] == "文書の MCP の入力に作業場所とセッションを入れた"


def test_normal_when_input_unparsable(run_hook: Callable[..., Any]) -> None:
    """stdin が JSON として読めなければ、何も出さず終了コード 0 で戻る（正常系）。"""
    # 実行
    result = run_hook("pre_tool_use", "not json", {})
    # 検証
    assert result.code == 0
    assert result.stdout == ""

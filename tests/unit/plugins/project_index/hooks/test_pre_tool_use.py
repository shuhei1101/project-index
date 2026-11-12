from __future__ import annotations

import io
import json
from collections.abc import Callable
from types import ModuleType

import pytest


def test_main(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """書き換えた入力を返す（正常系）。"""
    # 準備
    hook = load_hook("pre_tool_use")
    event = {
        "tool_name": "mcp__plugin_project-index_project-index__search_docs",
        "tool_input": {"query": "起動", "cwd": "/other"},
        "session_id": "s1",
        "cwd": "/repo",
        "agent_id": "a1",
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    # 実行
    code = hook.main()
    # 検証
    output = json.loads(capsys.readouterr().out)
    specific = output["hookSpecificOutput"]
    assert code == 0
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["updatedInput"]["cwd"] == "/repo"
    assert "permissionDecision" not in specific
    assert "permissionDecision" not in output


def test_main_when_input_unparsable(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """読めない入力では何も出さない（異常系）。"""
    # 準備
    hook = load_hook("pre_tool_use")
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    # 実行
    code = hook.main()
    # 検証
    assert code == 0
    assert capsys.readouterr().out == ""


def test_build_updated_input(load_hook: Callable[[str], ModuleType]) -> None:
    """エージェントが入れた値を上書きする（正常系）。"""
    # 準備
    hook = load_hook("pre_tool_use")
    tool_input = {"query": "起動", "cwd": "/other", "session_id": "x"}
    event = {
        "tool_input": tool_input,
        "cwd": "/repo",
        "session_id": "s1",
        "agent_id": "a1",
    }
    # 実行
    result = hook.build_updated_input(event)
    # 検証
    assert result == {"query": "起動", "cwd": "/repo", "session_id": "s1", "agent_id": "a1"}
    assert tool_input == {"query": "起動", "cwd": "/other", "session_id": "x"}


def test_build_updated_input_when_no_agent(load_hook: Callable[[str], ModuleType]) -> None:
    """メインのセッションでは agent_id を入れない（正常系）。"""
    # 準備
    hook = load_hook("pre_tool_use")
    event = {
        "tool_input": {"query": "起動", "agent_id": "fake"},
        "cwd": "/repo",
        "session_id": "s1",
    }
    # 実行
    result = hook.build_updated_input(event)
    # 検証
    assert "agent_id" not in result
    assert result["cwd"] == "/repo"
    assert result["session_id"] == "s1"

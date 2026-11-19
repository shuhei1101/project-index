from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import ModuleType

    import pytest


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """標準入力を、渡した文字列に差し替える。"""
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def test_main(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """返った文面を出す（正常系）。"""
    # 準備
    hook = load_hook("post_tool_use")
    target = tmp_path / "a.md"
    target.write_text("# a\n", encoding="utf-8")
    monkeypatch.setattr(hook, "query_notice", lambda event, paths: "管理用の YAML を確認する")
    _stdin(
        monkeypatch,
        json.dumps(
            {
                "session_id": "s1",
                "cwd": str(tmp_path),
                "tool_name": "Edit",
                "tool_input": {"file_path": str(target)},
            }
        ),
    )
    # 実行
    code = hook.main()
    # 検証
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "管理用の YAML を確認する",
        }
    }


def test_main_when_skipped_tool(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """文書の MCP のツールでは問い合わせない（正常系）。"""
    # 準備
    hook = load_hook("post_tool_use")
    target = tmp_path / "a.yaml"
    target.write_text("id: a\n", encoding="utf-8")

    def fail_query(event: dict[str, Any], paths: list[str]) -> str:
        message = "問い合わせてはいけない"
        raise AssertionError(message)

    monkeypatch.setattr(hook, "query_notice", fail_query)
    _stdin(
        monkeypatch,
        json.dumps(
            {
                "session_id": "s1",
                "cwd": str(tmp_path),
                "tool_name": "mcp__plugin_project-index_project-index__write_docs",
                "tool_input": {"worktree": str(tmp_path), "path": str(target)},
            }
        ),
    )
    # 実行
    code = hook.main()
    # 検証
    assert code == 0
    assert capsys.readouterr().out == ""


def test_main_when_input_unparsable(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """読めない入力では何も出さない（異常系）。"""
    # 準備
    hook = load_hook("post_tool_use")
    _stdin(monkeypatch, "not json")
    # 実行
    code = hook.main()
    # 検証
    assert code == 0
    assert capsys.readouterr().out == ""


def test_collect_paths(load_hook: Callable[[str], ModuleType], tmp_path: Path) -> None:
    """Edit の file_path を返す（正常系）。"""
    # 準備
    hook = load_hook("post_tool_use")
    target = tmp_path / "a.md"
    target.write_text("# a\n", encoding="utf-8")
    # 実行
    result = hook.collect_paths("Edit", {"file_path": str(target)}, str(tmp_path))
    # 検証
    assert result == [str(target)]


def test_collect_paths_when_mcp_tool(
    load_hook: Callable[[str], ModuleType], tmp_path: Path
) -> None:
    """MCP のツールの入れ子の文字列から集める（正常系）。"""
    # 準備
    hook = load_hook("post_tool_use")
    absolute = tmp_path / "a.md"
    absolute.write_text("# a\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    relative = tmp_path / "sub" / "b.md"
    relative.write_text("# b\n", encoding="utf-8")
    tool_input = {
        "target": str(absolute),
        "items": [{"path": "sub/b.md"}, {"path": str(tmp_path / "missing.md")}],
        "message": "パスでない文字列",
    }
    # 実行
    result = hook.collect_paths("mcp__test__write", tool_input, str(tmp_path))
    # 検証
    assert result == [str(absolute), str(relative)]


def test_collect_paths_when_other_tool(
    load_hook: Callable[[str], ModuleType], tmp_path: Path
) -> None:
    """対象外のツールは空（正常系）。"""
    # 準備
    hook = load_hook("post_tool_use")
    # 実行
    result = hook.collect_paths("Bash", {"command": f"touch {tmp_path}/a.md"}, str(tmp_path))
    # 検証
    assert result == []


def test_query_notice(
    load_hook: Callable[[str], ModuleType],
    context_server: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """応答の文面を返す（正常系）。"""
    # 準備
    hook = load_hook("post_tool_use")
    with context_server({"notices": [], "additional_context": "通知の文面"}) as server:
        monkeypatch.setenv("PROJECT_INDEX_PORT", str(server.port))
        # 実行
        result = hook.query_notice({"session_id": "s1"}, ["/repo/docs/a.md"])
    # 検証
    assert result == "通知の文面"
    assert server.bodies == [{"session_id": "s1", "paths": ["/repo/docs/a.md"]}]


def test_query_notice_when_timeout(
    load_hook: Callable[[str], ModuleType],
    context_server: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """打ち切ったら None（異常系）。"""
    # 準備
    hook = load_hook("post_tool_use")
    monkeypatch.setattr(hook, "NOTICE_TIMEOUT_SEC", 0.2)
    with context_server({"additional_context": "遅い文面"}, hold_sec=2.0) as server:
        monkeypatch.setenv("PROJECT_INDEX_PORT", str(server.port))
        # 実行
        result = hook.query_notice({"session_id": "s1"}, ["/repo/docs/a.md"])
    # 検証
    assert result is None

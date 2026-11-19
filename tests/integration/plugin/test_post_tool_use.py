from __future__ import annotations

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

HOOKS_DIR = Path(__file__).parents[3] / "plugins" / "project-index" / "hooks"
NOTICE = "書き込んだファイルは配信元の管理用の YAML の範囲にあります。"


def _hooks_with_notice_timeout(tmp_path: Path, seconds: float) -> Path:
    """`NOTICE_TIMEOUT_SEC` を `seconds` に差し替えたツール実行後のフックのコピーを置き、そのフォルダを返す。"""
    text = (HOOKS_DIR / "post_tool_use.py").read_text(encoding="utf-8")
    replaced = re.sub(
        r"^NOTICE_TIMEOUT_SEC = \d+$", f"NOTICE_TIMEOUT_SEC = {seconds}", text, flags=re.M
    )
    assert replaced != text
    folder = tmp_path / "hooks"
    folder.mkdir()
    (folder / "post_tool_use.py").write_text(replaced, encoding="utf-8")
    return folder


def _edit_event(tmp_path: Path) -> tuple[dict[str, Any], Path]:
    """存在するファイルを Edit した PostToolUse の入力と、そのファイルを返す。"""
    target = tmp_path / "docs" / "guide.md"
    target.parent.mkdir(parents=True)
    target.write_text("# guide\n", encoding="utf-8")
    event = {
        "session_id": "s1",
        "cwd": str(tmp_path),
        "tool_name": "Edit",
        "tool_input": {"file_path": str(target)},
    }
    return event, target


def test_normal(
    tmp_path: Path, run_hook: Callable[..., Any], context_server: Callable[..., Any]
) -> None:
    """Edit の file_path を送信し、返った文面を additionalContext で返す（正常系）。"""
    # 準備
    event, target = _edit_event(tmp_path)
    with context_server(response={"notices": [], "additional_context": NOTICE}) as server:
        # 実行
        result = run_hook("post_tool_use", event, {"PROJECT_INDEX_PORT": str(server.port)})
    # 検証
    assert result.code == 0
    assert server.paths == ["/_admin/post-write"]
    assert server.bodies == [{"session_id": "s1", "paths": [str(target)]}]
    assert result.output == {
        "hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": NOTICE}
    }


def test_normal_when_mcp_tool(
    tmp_path: Path, run_hook: Callable[..., Any], context_server: Callable[..., Any]
) -> None:
    """MCP のツールの引数の文字列の値のうち、存在するファイルのパスを集めて送信する（正常系）。"""
    # 準備
    absolute = tmp_path / "a.md"
    absolute.write_text("# a\n", encoding="utf-8")
    relative = tmp_path / "sub" / "b.md"
    relative.parent.mkdir()
    relative.write_text("# b\n", encoding="utf-8")
    event = {
        "session_id": "s1",
        "cwd": str(tmp_path),
        "tool_name": "mcp__test__write",
        "tool_input": {
            "target": str(absolute),
            "items": [{"path": "sub/b.md"}, {"path": str(tmp_path / "missing.md")}],
            "message": "パスでない文字列",
        },
    }
    with context_server(response={"notices": [], "additional_context": NOTICE}) as server:
        # 実行
        result = run_hook("post_tool_use", event, {"PROJECT_INDEX_PORT": str(server.port)})
    # 検証
    assert result.code == 0
    assert server.bodies == [{"session_id": "s1", "paths": [str(absolute), str(relative)]}]
    assert result.output["hookSpecificOutput"]["additionalContext"] == NOTICE


def test_normal_when_tool_not_queried(
    tmp_path: Path, run_hook: Callable[..., Any], context_server: Callable[..., Any]
) -> None:
    """文書の MCP のツールと、パスを持たない呼び出しでは問い合わせない（正常系）。"""
    # 準備
    target = tmp_path / "doc.yaml"
    target.write_text("id: doc\n", encoding="utf-8")
    write_docs = {
        "session_id": "s1",
        "cwd": str(tmp_path),
        "tool_name": "mcp__plugin_project-index_project-index__write_docs",
        "tool_input": {"worktree": str(tmp_path), "path": str(target)},
    }
    no_path = {
        "session_id": "s1",
        "cwd": str(tmp_path),
        "tool_name": "mcp__test__search",
        "tool_input": {"query": "パスでない文字列"},
    }
    with context_server(response={"notices": [], "additional_context": NOTICE}) as server:
        env = {"PROJECT_INDEX_PORT": str(server.port)}
        # 実行
        skipped = run_hook("post_tool_use", write_docs, env)
        empty = run_hook("post_tool_use", no_path, env)
    # 検証
    assert server.bodies == []
    assert (skipped.code, skipped.stdout) == (0, "")
    assert (empty.code, empty.stdout) == (0, "")


def test_normal_when_query_failed(
    tmp_path: Path, run_hook: Callable[..., Any], context_server: Callable[..., Any]
) -> None:
    """サーバーが返らなければ、何も出力せずに終了コード 0 で戻る（正常系）。"""
    # 準備
    event, _ = _edit_event(tmp_path)
    hooks_dir = _hooks_with_notice_timeout(tmp_path, 1)
    with context_server(hold_sec=5.0) as server:
        started = time.monotonic()
        # 実行
        result = run_hook(
            "post_tool_use", event, {"PROJECT_INDEX_PORT": str(server.port)}, hooks_dir=hooks_dir
        )
        elapsed = time.monotonic() - started
    # 検証
    assert result.code == 0
    assert result.stdout == ""
    assert elapsed < 2


def test_normal_when_input_unparsable(run_hook: Callable[..., Any]) -> None:
    """stdin が JSON として読めなければ何も出さず終了コード 0 で戻る（正常系）。"""
    # 実行
    result = run_hook("post_tool_use", "not json", {})
    # 検証
    assert result.code == 0
    assert result.stdout == ""

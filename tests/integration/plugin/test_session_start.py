from __future__ import annotations

import contextlib
import os
import re
import signal
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

HOOKS_DIR = Path(__file__).parents[3] / "plugins" / "project-index" / "hooks"
EVENT = {"session_id": "s1", "cwd": "/repo/sample", "source": "startup"}
CLEARED = {"session_id": "s1", "cwd": "/repo/sample", "source": "clear"}
COMPACTED = {"session_id": "s1", "cwd": "/repo/sample", "source": "compact"}


def _clone_with_recorder(tmp_path: Path) -> tuple[Path, Path, Path]:
    """起動の引数と PID を記録して待ち続ける偽の Python を持つクローンを作る。"""
    clone = tmp_path / "clone"
    python = clone / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    args_file = tmp_path / "args.txt"
    pid_file = tmp_path / "pid.txt"
    python.write_text(
        f'#!/bin/sh\necho "$@" > "{args_file}"\necho $$ > "{pid_file}"\nexec sleep 30\n',
        encoding="utf-8",
    )
    python.chmod(0o755)
    return clone, args_file, pid_file


def _hooks_with_forget_timeout(tmp_path: Path, seconds: int) -> Path:
    """`FORGET_TIMEOUT_SEC` を `seconds` に差し替えたセッション開始のフックのコピーを置き、そのフォルダを返す。"""
    source = HOOKS_DIR / "session_start.py"
    text = source.read_text(encoding="utf-8")
    replaced = re.sub(
        r"^FORGET_TIMEOUT_SEC = \d+$", f"FORGET_TIMEOUT_SEC = {seconds}", text, flags=re.M
    )
    assert replaced != text
    folder = tmp_path / "hooks"
    folder.mkdir()
    (folder / "session_start.py").write_text(replaced, encoding="utf-8")
    return folder


def _wait_for(path: Path, timeout_sec: float = 5) -> str:
    """ファイルができるまで待ち、中身を返す。"""
    deadline = time.monotonic() + timeout_sec
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return path.read_text(encoding="utf-8").strip()


def test_normal_when_server_listening(
    tmp_path: Path, run_hook: Callable[..., Any], context_server: Callable[..., Any]
) -> None:
    """つながったサーバーには何も依頼せず、文脈を入れずに戻る（正常系）。"""
    # 準備・実行
    with context_server() as server:
        result = run_hook(
            "session_start",
            EVENT,
            {
                "PROJECT_INDEX_PORT": str(server.port),
                "PROJECT_INDEX_CONFIG": str(tmp_path / "missing.yaml"),
            },
        )
    # 検証
    assert result.code == 0
    assert result.stdout == ""
    assert server.bodies == []


def test_normal_when_cleared(
    tmp_path: Path, run_hook: Callable[..., Any], context_server: Callable[..., Any]
) -> None:
    """`/clear` の後は `POST /_admin/session-start` で記録の削除を依頼し、文脈を入れずに戻る（正常系）。"""
    # 準備・実行
    with context_server() as server:
        result = run_hook(
            "session_start",
            CLEARED,
            {
                "PROJECT_INDEX_PORT": str(server.port),
                "PROJECT_INDEX_CONFIG": str(tmp_path / "missing.yaml"),
            },
        )
    # 検証
    assert result.code == 0
    assert result.stdout == ""
    assert server.bodies == [{"session_id": "s1", "reason": "clear"}]
    assert server.paths == ["/_admin/session-start"]


def test_normal_when_server_down(
    tmp_path: Path, run_hook: Callable[..., Any], free_port: Callable[[], int]
) -> None:
    """つながらなければ `project-index serve` を切り離して起動し、再接続を案内する（正常系）。"""
    # 準備
    clone, args_file, pid_file = _clone_with_recorder(tmp_path)
    settings = tmp_path / "settings.yaml"
    settings.write_text(f'version: "1"\nclone: {clone}\n', encoding="utf-8")
    started = time.monotonic()
    # 実行
    result = run_hook(
        "session_start",
        EVENT,
        {"PROJECT_INDEX_PORT": str(free_port()), "PROJECT_INDEX_CONFIG": str(settings)},
    )
    elapsed = time.monotonic() - started
    # 検証
    try:
        recorded = _wait_for(args_file)
        context = result.output["hookSpecificOutput"]["additionalContext"]
        assert result.code == 0
        assert recorded == "-m project_index serve"
        assert "/mcp" in context
        assert "再接続して" in context
        # 起動したプロセスは 30 秒動き続けるので、待たずに戻っている
        assert elapsed < 10
    finally:
        with contextlib.suppress(OSError, ValueError):
            os.kill(int(_wait_for(pid_file, 1)), signal.SIGTERM)


def test_normal_when_xdg_config_home_set(
    tmp_path: Path, run_hook: Callable[..., Any], free_port: Callable[[], int]
) -> None:
    """PROJECT_INDEX_CONFIG が無ければ XDG_CONFIG_HOME の下の端末の設定の clone で起動する（正常系）。"""
    # 準備
    xdg = tmp_path / "xdg"
    xdg_clone, xdg_args, xdg_pid = _clone_with_recorder(xdg)
    (xdg / "project-index").mkdir()
    (xdg / "project-index" / "settings.yaml").write_text(
        f'version: "1"\nclone: {xdg_clone}\n', encoding="utf-8"
    )
    home = tmp_path / "home"
    home_clone, home_args, home_pid = _clone_with_recorder(home)
    (home / ".config" / "project-index").mkdir(parents=True)
    (home / ".config" / "project-index" / "settings.yaml").write_text(
        f'version: "1"\nclone: {home_clone}\n', encoding="utf-8"
    )
    base = {"PROJECT_INDEX_PORT": str(free_port()), "PROJECT_INDEX_CONFIG": "", "HOME": str(home)}
    # 実行
    first = run_hook("session_start", EVENT, {**base, "XDG_CONFIG_HOME": str(xdg)})
    second = run_hook("session_start", EVENT, {**base, "XDG_CONFIG_HOME": "rel"})
    # 検証
    try:
        assert first.code == 0
        assert _wait_for(xdg_args) == "-m project_index serve"
        assert second.code == 0
        assert _wait_for(home_args) == "-m project_index serve"
    finally:
        for pid_file in (xdg_pid, home_pid):
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(_wait_for(pid_file, 1)), signal.SIGTERM)


def test_normal_when_terminal_config_missing(
    tmp_path: Path, run_hook: Callable[..., Any], free_port: Callable[[], int]
) -> None:
    """端末の設定が無ければ、理由と global-setup の案内を入れる（正常系）。"""
    # 準備
    config = tmp_path / "missing.yaml"
    # 実行
    result = run_hook(
        "session_start",
        EVENT,
        {"PROJECT_INDEX_PORT": str(free_port()), "PROJECT_INDEX_CONFIG": str(config)},
    )
    # 検証
    context = result.output["hookSpecificOutput"]["additionalContext"]
    assert result.code == 0
    assert str(config) in context
    assert "/project-index:global-setup" in context


def test_normal_when_forget_failed(
    tmp_path: Path, run_hook: Callable[..., Any], context_server: Callable[..., Any]
) -> None:
    """`POST /_admin/session-start` が `FORGET_TIMEOUT_SEC` 秒で返らなければ、削除できなかったことと打ち切った秒数・repeat_seen の案内を入れて戻る（正常系）。"""
    # 準備
    hooks_dir = _hooks_with_forget_timeout(tmp_path, 1)
    started = time.monotonic()
    # 実行
    with context_server(hold_sec=3) as server:
        result = run_hook(
            "session_start",
            COMPACTED,
            {
                "PROJECT_INDEX_PORT": str(server.port),
                "PROJECT_INDEX_CONFIG": str(tmp_path / "missing.yaml"),
            },
            hooks_dir=hooks_dir,
        )
    elapsed = time.monotonic() - started
    # 検証
    context = result.output["hookSpecificOutput"]["additionalContext"]
    assert result.code == 0
    assert elapsed < 2
    assert "削除できませんでした" in context
    assert "1 秒で打ち切りました" in context
    assert "repeat_seen: true で再取得できます" in context
    assert "起動しました" not in context

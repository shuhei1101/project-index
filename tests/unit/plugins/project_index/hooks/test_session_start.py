from __future__ import annotations

import io
import json
import socket
import time
import urllib.error
from contextlib import closing, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from types import ModuleType


def _free_port() -> int:
    """OS が払い出して閉じたポートの番号を返す。"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _listening() -> Generator[int]:
    """テストが `listen` しているポートの番号を渡す。"""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        yield int(sock.getsockname()[1])


def _stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """標準入力を、渡した文字列に差し替える。"""
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def test_main_when_listening(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """つながれば何も出さない（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    requested: list[tuple[int, dict[str, str]]] = []

    def fake_forget(port: int, payload: dict[str, str]) -> None:
        requested.append((port, payload))

    monkeypatch.setattr(hook, "is_listening", lambda port: True)
    monkeypatch.setattr(hook, "request_forget", fake_forget)
    _stdin(
        monkeypatch,
        json.dumps({"session_id": "s1", "cwd": "/repo", "source": "startup"}),
    )
    # 実行
    code = hook.main()
    # 検証
    assert code == 0
    assert capsys.readouterr().out == ""
    assert requested == []


def test_main_when_cleared(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """/clear の後は記録の削除を依頼し、何も出さない（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    requested: list[tuple[int, dict[str, str]]] = []

    def fake_forget(port: int, payload: dict[str, str]) -> None:
        requested.append((port, payload))

    monkeypatch.setattr(hook, "is_listening", lambda port: True)
    monkeypatch.setattr(hook, "request_forget", fake_forget)
    monkeypatch.setenv("PROJECT_INDEX_PORT", "8799")
    _stdin(
        monkeypatch,
        json.dumps({"session_id": "s1", "cwd": "/repo", "source": "clear"}),
    )
    # 実行
    code = hook.main()
    # 検証
    assert code == 0
    assert capsys.readouterr().out == ""
    assert requested == [(8799, {"session_id": "s1", "reason": "clear"})]


def test_main_when_down(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """つながらなければ起動して案内する（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    clone = tmp_path / "clone"
    (clone / ".venv" / "bin").mkdir(parents=True)
    (clone / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    config = tmp_path / "settings.yaml"
    config.write_text(f'version: "1"\nclone: {clone}\n', encoding="utf-8")
    started: list[Path] = []
    monkeypatch.setattr(hook, "is_listening", lambda port: False)
    monkeypatch.setattr(hook, "start_server", started.append)
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(config))
    _stdin(
        monkeypatch,
        json.dumps({"session_id": "s1", "cwd": "/repo", "source": "startup"}),
    )
    # 実行
    code = hook.main()
    # 検証
    output = json.loads(capsys.readouterr().out)
    assert code == 0
    assert started == [clone]
    assert output["hookSpecificOutput"]["additionalContext"] == hook.RECONNECT_GUIDE


def test_main_when_config_missing(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """端末の設定が無ければ global-setup を案内する（異常系）。"""
    # 準備
    hook = load_hook("session_start")
    config = tmp_path / "missing.yaml"
    started: list[Path] = []
    monkeypatch.setattr(hook, "is_listening", lambda port: False)
    monkeypatch.setattr(hook, "start_server", started.append)
    monkeypatch.setenv("PROJECT_INDEX_CONFIG", str(config))
    _stdin(
        monkeypatch,
        json.dumps({"session_id": "s1", "cwd": "/repo", "source": "startup"}),
    )
    # 実行
    code = hook.main()
    # 検証
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert code == 0
    assert str(config) in context
    assert "/project-index:global-setup" in context
    assert started == []


def test_main_when_forget_failed(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """記録の削除を依頼できなければ repeat_seen を案内する（異常系）。"""
    # 準備
    hook = load_hook("session_start")

    def failing_forget(port: int, payload: dict[str, str]) -> None:
        msg = "timed out"
        raise TimeoutError(msg)

    monkeypatch.setattr(hook, "is_listening", lambda port: True)
    monkeypatch.setattr(hook, "request_forget", failing_forget)
    _stdin(
        monkeypatch,
        json.dumps({"session_id": "s1", "cwd": "/repo", "source": "compact"}),
    )
    # 実行
    code = hook.main()
    # 検証
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert code == 0
    assert "3 秒で打ち切りました" in context
    assert "repeat_seen: true" in context


def test_main_when_input_unparsable(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """読めない入力では何も出さない（異常系）。"""
    # 準備
    hook = load_hook("session_start")
    _stdin(monkeypatch, "{")
    # 実行
    code = hook.main()
    # 検証
    assert code == 0
    assert capsys.readouterr().out == ""


def test_main_when_forget_refused(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """打ち切り以外の失敗は秒数を入れない（異常系）。"""
    # 準備
    hook = load_hook("session_start")

    def refused_forget(port: int, payload: dict[str, str]) -> None:
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(hook, "is_listening", lambda port: True)
    monkeypatch.setattr(hook, "request_forget", refused_forget)
    _stdin(
        monkeypatch,
        json.dumps({"session_id": "s1", "cwd": "/repo", "source": "clear"}),
    )
    # 実行
    code = hook.main()
    # 検証
    context = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert code == 0
    assert "Connection refused" in context
    assert "repeat_seen: true" in context
    assert "秒で打ち切りました" not in context


def test_is_listening(load_hook: Callable[[str], ModuleType]) -> None:
    """待ち受けているポート（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    # 実行・検証
    with _listening() as port:
        assert hook.is_listening(port) is True


def test_is_listening_when_closed(load_hook: Callable[[str], ModuleType]) -> None:
    """待ち受けていないポート（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    port = _free_port()
    # 実行
    result = hook.is_listening(port)
    # 検証
    assert result is False


def test_config_path(load_hook: Callable[[str], ModuleType]) -> None:
    """PROJECT_INDEX_CONFIG が優先（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    env = {"PROJECT_INDEX_CONFIG": "/tmp/x/settings.yaml", "XDG_CONFIG_HOME": "/tmp/c"}
    # 実行
    result = hook.config_path(env)
    # 検証
    assert result == Path("/tmp/x/settings.yaml")


def test_config_path_when_xdg_config_home_set(load_hook: Callable[[str], ModuleType]) -> None:
    """XDG_CONFIG_HOME の下（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    env = {"XDG_CONFIG_HOME": "/tmp/c"}
    # 実行
    result = hook.config_path(env)
    # 検証
    assert result == Path("/tmp/c/project-index/settings.yaml")


@pytest.mark.parametrize("env", [{}, {"XDG_CONFIG_HOME": ""}, {"XDG_CONFIG_HOME": "rel"}])
def test_config_path_when_unset_or_relative(
    load_hook: Callable[[str], ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
) -> None:
    """未設定・空の文字列・相対パスは既定（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    monkeypatch.setenv("HOME", "/home/u")
    # 実行
    result = hook.config_path(env)
    # 検証
    assert result == Path("/home/u/.config/project-index/settings.yaml")


def test_read_clone(load_hook: Callable[[str], ModuleType], tmp_path: Path) -> None:
    """引用符と ~ を扱う（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    config = tmp_path / "settings.yaml"
    config.write_text(
        'version: "1"\nclone: "~/project-index"  # クローン\nsources:\n  - id: a\n    clone: /other\n',
        encoding="utf-8",
    )
    # 実行
    result = hook.read_clone(config)
    # 検証
    assert result == Path.home() / "project-index"


def test_read_clone_when_missing(load_hook: Callable[[str], ModuleType], tmp_path: Path) -> None:
    """行かファイルが無い（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    no_line = tmp_path / "no_line.yaml"
    no_line.write_text('version: "1"\n', encoding="utf-8")
    # 実行
    result_no_line = hook.read_clone(no_line)
    result_no_file = hook.read_clone(tmp_path / "missing.yaml")
    # 検証
    assert result_no_line is None
    assert result_no_file is None


@pytest.mark.filterwarnings("ignore:subprocess .* is still running:ResourceWarning")
def test_start_server(load_hook: Callable[[str], ModuleType], tmp_path: Path) -> None:
    """切り離して起動する（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    clone = tmp_path / "clone"
    python = clone / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    record = tmp_path / "args.txt"
    python.write_text(f'#!/bin/sh\necho "$@" > "{record}"\n', encoding="utf-8")
    python.chmod(0o755)
    # 実行
    hook.start_server(clone)
    # 検証
    deadline = time.monotonic() + 5
    while not record.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert record.read_text(encoding="utf-8").strip() == "-m project_index serve"


def test_start_server_when_no_venv(load_hook: Callable[[str], ModuleType], tmp_path: Path) -> None:
    """.venv が無い（異常系）。"""
    # 準備
    hook = load_hook("session_start")
    # 実行・検証
    with pytest.raises(FileNotFoundError):
        hook.start_server(tmp_path)


def test_request_forget(
    load_hook: Callable[[str], ModuleType],
    context_server: Callable[..., Any],
) -> None:
    """本文を POST する（正常系）。"""
    # 準備
    hook = load_hook("session_start")
    payload = {"session_id": "s1", "reason": "clear"}
    # 実行
    with context_server({"forgotten": True}) as server:
        result = hook.request_forget(server.port, payload)
    # 検証
    assert result is None
    assert server.bodies == [payload]


def test_request_forget_when_timeout(
    load_hook: Callable[[str], ModuleType],
    context_server: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`FORGET_TIMEOUT_SEC` で打ち切る（異常系）。"""
    # 準備
    hook = load_hook("session_start")
    monkeypatch.setattr(hook, "FORGET_TIMEOUT_SEC", 1)
    payload: dict[str, Any] = {"session_id": "s1", "reason": "compact"}
    started = time.monotonic()
    # 実行
    with context_server({"forgotten": True}, hold_sec=2) as server, pytest.raises(TimeoutError):
        hook.request_forget(server.port, payload)
    # 検証
    assert time.monotonic() - started < 2

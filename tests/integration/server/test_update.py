from __future__ import annotations

import json
import os
import socket
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from project_index.shared.version import RUNNING_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable

SETTINGS_QUERY = "src/project_index/features/settings/query.py"
MIGRATION_STEPS = (
    "steps:\n  - op: add\n    path: port\n    value: 8786\n    description: ポートを足す\n"
)
SLOW_CONFIG = (
    "name: slow\n"
    "documents:\n"
    "  - id: note\n"
    "    paths: [docs/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "    converter: sleepy\n"
    "converters:\n"
    "  - id: sleepy\n"
    "    run: [python3, scripts/sleepy.py]\n"
)
SLEEPY = "import sys\nimport time\nsys.stdin.read()\ntime.sleep(3)\nprint('# 眠ってから返した')\n"
UPDATE_CALL = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "update", "arguments": {}},
    }
)
NO_RESTART_WAIT_SEC = 3
NPM_DEVELOP = "install -g github:shuhei1101/mdmark#develop"
REINSTALLED_DEVELOP = {"ref": "develop", "reinstalled": True}


@dataclass(frozen=True)
class FakeTools:
    """`PATH` の先頭に置いた `npm`・`mdmark` の偽物と、`npm` が受けた引数の記録。"""

    log: Path

    def npm_calls(self) -> list[str]:
        """`npm` が受けた引数を、呼ばれた順に 1 回 1 行で返す。"""
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()


def _write_script(path: Path, body: str) -> None:
    """実行できるシェルスクリプトを書く。"""
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def fake_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeTools]:
    """`npm`（と任意で `mdmark`）の偽物を `PATH` の先頭に置く関数を返す。

    元の `PATH` から `mdmark` を持つフォルダを除くので、端末の mdmark の CLI は見えない。
    """

    def _install(*, mdmark: bool = True, npm_exit: int = 0, npm_stderr: str = "") -> FakeTools:
        bin_dir = tmp_path / "fake-bin"
        bin_dir.mkdir(exist_ok=True)
        log = tmp_path / "npm-calls.log"
        stderr = f"echo '{npm_stderr}' >&2\n" if npm_stderr else ""
        _write_script(bin_dir / "npm", f'echo "$*" >> {log}\n{stderr}exit {npm_exit}\n')
        if mdmark:
            _write_script(bin_dir / "mdmark", "exit 0\n")
        rest = [
            folder
            for folder in os.environ.get("PATH", "").split(os.pathsep)
            if folder and not (Path(folder) / "mdmark").exists()
        ]
        monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), *rest]))
        return FakeTools(log)

    return _install


def _slow_update(port: int) -> tuple[socket.socket, bytes]:
    """`update` の要求の本文を途中まで送った接続と、残りの本文を返す。"""
    body = UPDATE_CALL.encode("utf-8")
    head = (
        "POST /_admin/mcp/ HTTP/1.1\r\n"
        f"Host: 127.0.0.1:{port}\r\n"
        "Accept: application/json, text/event-stream\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    sock = socket.create_connection(("127.0.0.1", port), timeout=30)
    sock.sendall(head + body[:10])
    return sock, body[10:]


def _read_result(sock: socket.socket) -> dict[str, Any]:
    """接続が閉じるまで応答を読み、JSON-RPC の結果の辞書を返す。"""
    chunks: list[bytes] = []
    while chunk := sock.recv(65536):
        chunks.append(chunk)
    payload = b"".join(chunks).split(b"\r\n\r\n", 1)[1]
    result: dict[str, Any] = json.loads(payload)["result"]
    return result


def test_normal(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
    wait_for_restart: Callable[..., None],
    fake_tools: Callable[..., FakeTools],
) -> None:
    """新しい commit を取り込み、依存を入れ直して起動し直す（正常系）。"""
    # 準備
    tools = fake_tools()
    settings = write_settings(make_source("sample"))
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
    started_head = project_index_clone.head()
    upstream = project_index_clone.push_upstream(project_index_clone.bump_version("0.3.0"), "bump")
    started = started_count(state_dir)
    # 実行
    with httpx.Client(timeout=300) as client:
        result = call_tool(client, port, "/_admin/mcp/", "update")
    wait_for_restart(state_dir, port, started)
    with httpx.Client(timeout=30) as client:
        status = call_tool(client, port, "/_admin/mcp/", "status", format="json")
    # 検証
    assert result["structuredContent"] == {
        "previous_version": RUNNING_VERSION,
        "version": "0.3.0",
        "updated": True,
        "migration_needed": False,
        "restarting": True,
        "previous_commit": started_head,
        "commit": upstream,
        "mdmark": REINSTALLED_DEVELOP,
    }
    assert project_index_clone.head() == upstream
    assert status["structuredContent"]["version"] == "0.3.0"
    assert tools.npm_calls() == [NPM_DEVELOP]


def test_normal_when_up_to_date(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
    fake_tools: Callable[..., FakeTools],
) -> None:
    """上流に新しい commit が無いと、クローンを変えずに mdmark の CLI だけを入れ直して返す（正常系）。"""
    # 準備
    tools = fake_tools()
    settings = write_settings(make_source("sample"))
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
    started = started_count(state_dir)
    head = project_index_clone.head()
    # 実行
    with httpx.Client(timeout=300) as client:
        result = call_tool(client, port, "/_admin/mcp/", "update")
    time.sleep(NO_RESTART_WAIT_SEC)
    # 検証
    data = result["structuredContent"]
    assert data["updated"] is False
    assert data["restarting"] is False
    assert data["version"] == data["previous_version"]
    assert data["commit"] == head
    assert data["previous_commit"] == head
    assert data["mdmark"] == REINSTALLED_DEVELOP
    assert tools.npm_calls() == [NPM_DEVELOP]
    assert project_index_clone.head() == head
    assert started_count(state_dir) == started
    assert process.poll() is None


def test_normal_when_running_process_stale(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
    wait_for_restart: Callable[..., None],
    fake_tools: Callable[..., FakeTools],
) -> None:
    """取り込む commit が無くても、クローンの HEAD が起動した commit と違えば、依存を入れ直して起動し直す（正常系）。"""
    # 準備
    tools = fake_tools()
    settings = write_settings(make_source("sample"))
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
    started_head = project_index_clone.head()
    upstream = project_index_clone.push_upstream(project_index_clone.bump_version("0.3.0"), "bump")
    project_index_clone.run_git(project_index_clone.clone, "pull", "--ff-only")
    started = started_count(state_dir)
    # 実行
    with httpx.Client(timeout=300) as client:
        result = call_tool(client, port, "/_admin/mcp/", "update")
    wait_for_restart(state_dir, port, started)
    with httpx.Client(timeout=30) as client:
        status = call_tool(client, port, "/_admin/mcp/", "status", format="json")
    # 検証
    assert result["structuredContent"] == {
        "previous_version": RUNNING_VERSION,
        "version": "0.3.0",
        "updated": False,
        "migration_needed": False,
        "restarting": True,
        "previous_commit": started_head,
        "commit": upstream,
        "mdmark": REINSTALLED_DEVELOP,
    }
    assert started_head != upstream
    assert status["structuredContent"]["commit"] == upstream
    assert status["structuredContent"]["version"] == "0.3.0"
    assert tools.npm_calls() == [NPM_DEVELOP]


def test_normal_when_migration_needed(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
    fake_tools: Callable[..., FakeTools],
) -> None:
    """新しいバージョンに移し替えの手順があると、再起動せずに返す（正常系）。"""
    # 準備
    tools = fake_tools()
    settings = write_settings(make_source("sample"))
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
    query = (project_index_clone.work / SETTINGS_QUERY).read_text(encoding="utf-8")
    project_index_clone.push_upstream(
        {
            **project_index_clone.bump_version("0.3.0"),
            SETTINGS_QUERY: query.replace('SETTINGS_VERSION = "1"', 'SETTINGS_VERSION = "2"'),
            "src/project_index/migrations/settings/2/steps.yaml": MIGRATION_STEPS,
        },
        "migration",
    )
    started = started_count(state_dir)
    before = settings.read_text(encoding="utf-8")
    # 実行
    with httpx.Client(timeout=300) as client:
        result = call_tool(client, port, "/_admin/mcp/", "update")
    time.sleep(NO_RESTART_WAIT_SEC)
    with httpx.Client(timeout=30) as client:
        status = call_tool(client, port, "/_admin/mcp/", "status", format="json")
    # 検証
    data = result["structuredContent"]
    assert data["updated"] is True
    assert data["migration_needed"] is True
    assert data["restarting"] is False
    assert data["mdmark"] == REINSTALLED_DEVELOP
    assert tools.npm_calls() == [NPM_DEVELOP]
    assert settings.read_text(encoding="utf-8") == before
    assert status["structuredContent"]["version"] == RUNNING_VERSION
    assert started_count(state_dir) == started


def test_error_when_pull_fails(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
    fake_tools: Callable[..., FakeTools],
) -> None:
    """fast-forward できないと、クローンに触らず再起動もしない（異常系）。"""
    # 準備
    tools = fake_tools()
    settings = write_settings(make_source("sample"))
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
    project_index_clone.run_git(project_index_clone.clone, "commit", "--allow-empty", "-m", "local")
    head = project_index_clone.head()
    project_index_clone.push_upstream(project_index_clone.bump_version("0.3.0"), "upstream")
    started = started_count(state_dir)
    # 実行
    with httpx.Client(timeout=300) as client:
        result = call_tool(client, port, "/_admin/mcp/", "update")
    time.sleep(NO_RESTART_WAIT_SEC)
    # 検証
    text = result["content"][0]["text"]
    assert result["isError"] is True
    assert text.startswith("UpdateFailedError")
    assert "git pull --ff-only" in text
    assert "fast-forward" in text
    assert tools.npm_calls() == []
    assert project_index_clone.head() == head
    assert started_count(state_dir) == started
    assert process.poll() is None


def test_error_when_restart_in_progress(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
    wait_for_restart: Callable[..., None],
    sample_file_set: Callable[..., dict[str, str]],
) -> None:
    """`restart` の停止を待っている間に `update` を呼ぶと、クローンに触らず断る（異常系）。"""
    # 準備
    files = sample_file_set(**{"project-index.yaml": SLOW_CONFIG, "scripts/sleepy.py": SLEEPY})
    slow = make_source("slow", files, git=False)
    settings = write_settings(slow, extra="script_timeout_sec: 4")
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
    head = project_index_clone.head()
    project_index_clone.push_upstream(project_index_clone.bump_version("0.3.0"), "upstream")
    started = started_count(state_dir)

    def convert() -> None:
        with httpx.Client(timeout=30) as client:
            call_tool(
                client,
                port,
                "/_admin/mcp/",
                "try_convert",
                path=str(slow.folder),
                file="docs/doc-1.yaml",
            )

    converting = threading.Thread(target=convert)
    # 実行（眠る変換の途中で、update の要求を送りかけたまま restart を呼び、残りを送る）
    converting.start()
    time.sleep(1)
    sock, rest = _slow_update(port)
    with httpx.Client(timeout=30) as client:
        call_tool(client, port, "/_admin/mcp/", "restart")
    time.sleep(0.3)
    sock.sendall(rest)
    result = _read_result(sock)
    sock.close()
    converting.join(timeout=60)
    wait_for_restart(state_dir, port, started)
    # 検証
    assert result["isError"] is True
    assert result["content"][0]["text"].startswith("RestartInProgressError")
    assert project_index_clone.head() == head


def test_normal_when_mdmark_absent(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
    wait_for_restart: Callable[..., None],
    fake_tools: Callable[..., FakeTools],
) -> None:
    """`PATH` に mdmark の CLI が無いと、入れ直さずに更新する（正常系）。"""
    # 準備
    tools = fake_tools(mdmark=False)
    settings = write_settings(make_source("sample"))
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
    project_index_clone.push_upstream(project_index_clone.bump_version("0.3.0"), "bump")
    started = started_count(state_dir)
    # 実行
    with httpx.Client(timeout=300) as client:
        result = call_tool(client, port, "/_admin/mcp/", "update")
    wait_for_restart(state_dir, port, started)
    # 検証
    data = result["structuredContent"]
    assert data["updated"] is True
    assert data["restarting"] is True
    assert "mdmark" not in data
    assert tools.npm_calls() == []


def test_normal_when_mdmark_reinstall_fails(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
    wait_for_restart: Callable[..., None],
    fake_tools: Callable[..., FakeTools],
) -> None:
    """`npm` が失敗しても、理由を応答に入れて更新と再起動を続ける（正常系）。"""
    # 準備
    tools = fake_tools(npm_exit=1, npm_stderr="npm error code ENOTFOUND")
    settings = write_settings(make_source("sample"), extra="mdmark_ref: v0.13.0")
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
    project_index_clone.push_upstream(project_index_clone.bump_version("0.3.0"), "bump")
    started = started_count(state_dir)
    # 実行
    with httpx.Client(timeout=300) as client:
        result = call_tool(client, port, "/_admin/mcp/", "update")
    wait_for_restart(state_dir, port, started)
    with httpx.Client(timeout=30) as client:
        status = call_tool(client, port, "/_admin/mcp/", "status", format="json")
    # 検証
    data = result["structuredContent"]
    assert result.get("isError") is not True
    assert data["updated"] is True
    assert data["restarting"] is True
    assert data["mdmark"]["ref"] == "v0.13.0"
    assert data["mdmark"]["reinstalled"] is False
    assert "npm install -g github:shuhei1101/mdmark#v0.13.0" in data["mdmark"]["error"]
    assert "npm error code ENOTFOUND" in data["mdmark"]["error"]
    assert tools.npm_calls() == ["install -g github:shuhei1101/mdmark#v0.13.0"]
    assert status["structuredContent"]["version"] == "0.3.0"


def test_error_when_terminal_config_invalid(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
    fake_tools: Callable[..., FakeTools],
) -> None:
    """端末の設定がスキーマに違反すると、クローンに触らずに違反を返す（異常系）。"""
    # 準備
    tools = fake_tools()
    settings = write_settings(make_source("sample"))
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
    head = project_index_clone.head()
    project_index_clone.push_upstream(project_index_clone.bump_version("0.3.0"), "upstream")
    settings.write_text(settings.read_text(encoding="utf-8") + "mdmark_ref: -x\n", encoding="utf-8")
    started = started_count(state_dir)
    # 実行
    with httpx.Client(timeout=300) as client:
        result = call_tool(client, port, "/_admin/mcp/", "update")
    time.sleep(NO_RESTART_WAIT_SEC)
    # 検証
    text = result["content"][0]["text"]
    assert result["isError"] is True
    assert text.startswith("TerminalConfigInvalidError")
    assert "mdmark_ref" in text
    assert project_index_clone.head() == head
    assert tools.npm_calls() == []
    assert started_count(state_dir) == started
    assert process.poll() is None

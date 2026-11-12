from __future__ import annotations

import json
import socket
import threading
import time
from typing import TYPE_CHECKING, Any

import httpx

from project_index.shared.version import RUNNING_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

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
) -> None:
    """新しい commit を取り込み、依存を入れ直して起動し直す（正常系）。"""
    # 準備
    settings = write_settings(make_source("sample"))
    state_dir = settings.parent / "state"
    port = free_port()
    process = start_serve_from_clone(project_index_clone.clone, settings, port)
    wait_until_serving(process, port)
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
    }
    assert project_index_clone.head() == upstream
    assert status["structuredContent"]["version"] == "0.3.0"


def test_normal_when_up_to_date(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
) -> None:
    """上流に新しい commit が無ければ、何も変えずに返す（正常系）。"""
    # 準備
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
    assert project_index_clone.head() == head
    assert started_count(state_dir) == started
    assert process.poll() is None


def test_normal_when_migration_needed(
    make_source: Callable[..., Any],
    write_settings: Callable[..., Path],
    free_port: Callable[[], int],
    project_index_clone: Any,
    start_serve_from_clone: Callable[..., Any],
    wait_until_serving: Callable[..., None],
    call_tool: Callable[..., dict[str, Any]],
    started_count: Callable[[Path], int],
) -> None:
    """新しいバージョンに移し替えの手順があると、再起動せずに返す（正常系）。"""
    # 準備
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
) -> None:
    """fast-forward できないと、クローンに触らず再起動もしない（異常系）。"""
    # 準備
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

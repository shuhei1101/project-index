from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

HOOKS_DIR = Path(__file__).parents[3] / "plugins" / "project-index" / "hooks"


@dataclass
class HookRun:
    """フックを子プロセスで実行した結果。"""

    code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> dict[str, Any]:
        """標準出力を JSON として読んだ値を返す。"""
        value: dict[str, Any] = json.loads(self.stdout)
        return value


@pytest.fixture
def run_hook() -> Callable[..., HookRun]:
    """プラグインのフックを、標準入力に JSON を渡して子プロセスで実行する関数を返す。

    `hooks_dir` は、定数を差し替えたフックのコピーを置いたフォルダを渡すときに使う。
    """

    def _run(
        name: str,
        event: dict[str, Any] | str,
        env: dict[str, str],
        *,
        hooks_dir: Path = HOOKS_DIR,
    ) -> HookRun:
        text = event if isinstance(event, str) else json.dumps(event)
        result = subprocess.run(
            [sys.executable, str(hooks_dir / f"{name}.py")],
            input=text,
            capture_output=True,
            text=True,
            env={**os.environ, **env},
            timeout=30,
            check=False,
        )
        return HookRun(result.returncode, result.stdout, result.stderr)

    return _run


@pytest.fixture
def free_port() -> Callable[[], int]:
    """今は空いている 127.0.0.1 のポートを返す関数を返す。"""

    def _find() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    return _find


@dataclass
class ContextServer:
    """`POST /_admin/session-start` を真似る HTTP サーバーのポートと、受けた本文・パス。"""

    port: int
    bodies: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    paths: list[str] = field(default_factory=list[str])


@pytest.fixture
def context_server() -> Callable[..., AbstractContextManager[ContextServer]]:
    """決めた応答を返す HTTP サーバーを一時のポートで立てる関数を返す。"""

    @contextmanager
    def _serve(*, hold_sec: float = 0.0) -> Generator[ContextServer]:
        released = threading.Event()
        holder: list[ContextServer] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                holder[0].bodies.append(json.loads(self.rfile.read(length)))
                holder[0].paths.append(self.path)
                # 応答しない設定のときは、テストが終わるまで待つ
                if hold_sec:
                    released.wait(hold_sec)
                payload = json.dumps({"forgotten": True}).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    # フックが打ち切って閉じた接続への書き込み
                    return

            def log_message(self, format: str, *args: Any) -> None:
                return

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        httpd.daemon_threads = True
        holder.append(ContextServer(int(httpd.server_address[1])))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield holder[0]
        finally:
            released.set()
            httpd.shutdown()
            httpd.server_close()
            thread.join()

    return _serve

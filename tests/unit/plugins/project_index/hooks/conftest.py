from __future__ import annotations

import importlib.util
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

HOOKS_DIR = Path(__file__).parents[5] / "plugins" / "project-index" / "hooks"


@pytest.fixture
def load_hook() -> Callable[[str], ModuleType]:
    """プラグインのフックのファイルを、ファイル名からモジュールとして読む関数を返す。"""

    def _load(name: str) -> ModuleType:
        spec = importlib.util.spec_from_file_location(f"hook_{name}", HOOKS_DIR / f"{name}.py")
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


class ReceivedBodies:
    """`POST /_admin/session-start` を真似る HTTP サーバーのポートと、受けた本文。"""

    def __init__(self, port: int) -> None:
        self.port = port
        self.bodies: list[dict[str, Any]] = []


@pytest.fixture
def context_server() -> Callable[..., AbstractContextManager[ReceivedBodies]]:
    """決めた応答を返す HTTP サーバーを一時のポートで立てる関数を返す。"""

    @contextmanager
    def _serve(
        response: dict[str, Any] | None = None, *, hold_sec: float = 0.0
    ) -> Iterator[ReceivedBodies]:
        released = threading.Event()
        received: list[ReceivedBodies] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                received[0].bodies.append(json.loads(self.rfile.read(length)))
                # 応答しない設定のときは、テストが終わるまで待つ
                if hold_sec:
                    released.wait(hold_sec)
                payload = json.dumps(response or {}).encode("utf-8")
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    # 呼び出し側が打ち切って閉じた接続への書き込み
                    return

            def log_message(self, format: str, *args: Any) -> None:
                return

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        httpd.daemon_threads = True
        received.append(ReceivedBodies(int(httpd.server_address[1])))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield received[0]
        finally:
            released.set()
            httpd.shutdown()
            httpd.server_close()
            thread.join()

    return _serve

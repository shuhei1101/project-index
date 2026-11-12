"""再起動の要求を受けて uvicorn を止める制御。"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

from project_index.features.lifecycle.types import RestartResult
from project_index.shared.errors import RestartInProgressError

if TYPE_CHECKING:
    import uvicorn

logger = logging.getLogger(__name__)


class RestartControl:
    """再起動の要求を 1 回だけ受け、uvicorn に停止を伝える。"""

    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None
        self._requested = False
        self._lock = threading.Lock()
        # `update_clone` が非ブロッキングで取り、更新の途中の他の `update` を断る
        self.update_lock = threading.Lock()

    def attach(self, server: uvicorn.Server) -> None:
        """停止を伝える uvicorn のサーバーを控える。"""
        self._server = server

    def request(self) -> RestartResult:
        """再起動を要求済みにし、uvicorn に停止を伝える。"""
        with self._lock:
            # 前の要求の再起動がまだ終わっていない
            if self._requested:
                raise RestartInProgressError(
                    message="再起動の途中です",
                    next_steps=["/mcp で再接続して status を呼んでください"],
                )
            self._requested = True
            # 待ち受けを閉じて処理中の要求を待たせる（応答は返ってから止まる）
            if self._server is not None:
                self._server.should_exit = True
        logger.info("再起動を始める（pid %s）", os.getpid())
        return RestartResult(pid=os.getpid(), restarting=True)

    @property
    def requested(self) -> bool:
        """再起動を要求されたか。"""
        with self._lock:
            return self._requested

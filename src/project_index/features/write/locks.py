"""配信元ごとの排他。"""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


class SourceLocks:
    """書き込み・削除を配信元ごとに 1 つずつにする。"""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def hold(self, source_id: str) -> AbstractContextManager[None]:
        """配信元の排他を握るコンテキストマネージャを返す。"""
        with self._guard:
            lock = self._locks.setdefault(source_id, threading.Lock())
        return self._hold(lock)

    @staticmethod
    @contextmanager
    def _hold(lock: threading.Lock) -> Generator[None]:
        """排他を握り、抜けるときに放す。"""
        with lock:
            yield

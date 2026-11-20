"""配信元ごとの排他と、リポジトリごとの排他。"""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING

from project_index.shared.errors import WriteDeadlineExceededError

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


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


class RepositoryLocks:
    """直コミットの取得からプッシュまでを、リポジトリごとに 1 つずつにする。"""

    def __init__(self) -> None:
        self._locks: dict[Path, threading.Lock] = {}
        self._guard = threading.Lock()

    def hold(self, repo: Path, *, timeout: float | None = None) -> AbstractContextManager[None]:
        """リポジトリの排他を、待ち時間の上限つきで握るコンテキストマネージャを返す。"""
        with self._guard:
            lock = self._locks.setdefault(repo, threading.Lock())
        return self._hold(lock, timeout)

    @staticmethod
    @contextmanager
    def _hold(lock: threading.Lock, timeout: float | None) -> Generator[None]:
        """上限まで待って握り、抜けるときに放す。"""
        # 上限が無ければ待ち続け、あれば上限までに握れなければ期限の超過にする
        acquired = lock.acquire() if timeout is None else lock.acquire(timeout=max(0.0, timeout))
        if not acquired:
            waited = round(timeout or 0, 1)
            raise WriteDeadlineExceededError(
                message=(
                    f"書き込みの期限（残り {waited:g} 秒）を超えたため、"
                    f"ファイルを書き換えずに止めました（経過 {waited:g} 秒）"
                ),
                deadline_sec=waited,
                elapsed_sec=waited,
                next_steps=["同じリポジトリへの直コミットが終わってから再実行してください"],
            )
        try:
            yield
        finally:
            lock.release()

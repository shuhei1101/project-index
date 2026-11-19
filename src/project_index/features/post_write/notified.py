"""会話キーごとの、書き込みの後の通知をしたパスの記録。"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from project_index.features.seen.types import SessionKey


class NotifiedStore:
    """会話キーごとに通知したパスをプロセスのメモリに記録する（再起動で消える）。"""

    def __init__(self) -> None:
        self._records: dict[SessionKey, set[str]] = {}
        self._lock = threading.Lock()

    def take_new(self, key: SessionKey, paths: Sequence[str]) -> list[str]:
        """記録に無いパスだけを渡した順に返し、返したパスを記録に追加する。"""
        with self._lock:
            recorded = self._records.setdefault(key, set())
            fresh: list[str] = []
            for path in paths:
                # 記録済みか、同じ呼び出しの中で既に集めたパスは除く
                if path in recorded:
                    continue
                recorded.add(path)
                fresh.append(path)
            return fresh

    def forget(self, key: SessionKey) -> int:
        """1 つの会話キーの記録を全て消し、消したパスの数を返す。"""
        with self._lock:
            return len(self._records.pop(key, set()))

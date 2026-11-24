"""配信元ごとの排他と、リポジトリごとの排他と、実行スロットの外で待つ書き込みの関所。"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from project_index.shared.errors import WriteDeadlineExceededError
from project_index.shared.runtime import current_record

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from project_index.shared.deadline import Deadline

# 排他を握れなかったときに添える次の手順
SOURCE_NEXT_STEP = "同じ配信元への書き込みが終わってから再実行してください"
REPOSITORY_NEXT_STEP = "同じリポジトリへの直コミットが終わってから再実行してください"


def _deadline_exceeded(waited: float, next_step: str) -> WriteDeadlineExceededError:
    """排他を待ち時間の上限までに握れなかったときの期限の超過を作る。"""
    rounded = round(waited, 1)
    return WriteDeadlineExceededError(
        message=(
            f"書き込みの期限（残り {rounded:g} 秒）を超えたため、"
            f"ファイルを書き換えずに止めました（経過 {rounded:g} 秒）"
        ),
        deadline_sec=rounded,
        elapsed_sec=rounded,
        next_steps=[next_step],
    )


@contextmanager
def _hold_lock(lock: threading.Lock, timeout: float | None, next_step: str) -> Generator[None]:
    """上限まで待って握り、抜けるときに放す。"""
    # 上限が無ければ待ち続け、あれば上限までに握れなければ期限の超過にする
    acquired = lock.acquire() if timeout is None else lock.acquire(timeout=max(0.0, timeout))
    if not acquired:
        raise _deadline_exceeded(timeout or 0, next_step)
    try:
        yield
    finally:
        lock.release()


class SourceLocks:
    """書き込み・削除を配信元ごとに 1 つずつにする。"""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def hold(self, source_id: str, *, timeout: float | None = None) -> AbstractContextManager[None]:
        """配信元の排他を、待ち時間の上限つきで握るコンテキストマネージャを返す。"""
        with self._guard:
            lock = self._locks.setdefault(source_id, threading.Lock())
        return _hold_lock(lock, timeout, SOURCE_NEXT_STEP)


class RepositoryLocks:
    """直コミットの取得からプッシュまでを、リポジトリごとに 1 つずつにする。"""

    def __init__(self) -> None:
        self._locks: dict[Path, threading.Lock] = {}
        self._guard = threading.Lock()

    def hold(self, repo: Path, *, timeout: float | None = None) -> AbstractContextManager[None]:
        """リポジトリの排他を、待ち時間の上限つきで握るコンテキストマネージャを返す。"""
        with self._guard:
            lock = self._locks.setdefault(repo, threading.Lock())
        return _hold_lock(lock, timeout, REPOSITORY_NEXT_STEP)


@dataclass(frozen=True, slots=True)
class WriteLockKeys:
    """1 回の書き込み・削除・直コミットが握る排他のキー（リポジトリと配信元）。"""

    # リポジトリごとの排他を握らない呼び出しは None
    repo: Path | None
    source_id: str


class WriteGates:
    """文書の MCP の実行スロットに入る前に、同じリポジトリ・同じ配信元への書き込みを 1 つずつ通す。

    イベントループの中だけで読み書きするため、辞書は排他を持たない。
    """

    def __init__(self) -> None:
        self._repos: dict[Path, asyncio.Lock] = {}
        self._sources: dict[str, asyncio.Lock] = {}

    @contextlib.asynccontextmanager
    async def hold(self, keys: WriteLockKeys, deadline: Deadline) -> AsyncGenerator[None]:
        """キーのリポジトリ・配信元の順に関所を、期限までの残りの時間だけ待って握る。"""
        # 中の排他と同じく、リポジトリ → 配信元の順に握る
        gates: list[asyncio.Lock] = []
        if keys.repo is not None:
            gates.append(self._repos.setdefault(keys.repo, asyncio.Lock()))
        gates.append(self._sources.setdefault(keys.source_id, asyncio.Lock()))
        held: list[asyncio.Lock] = []
        waited_from = time.monotonic()
        remaining = deadline.remaining()
        try:
            try:
                async with asyncio.timeout(remaining):
                    for gate in gates:
                        await gate.acquire()
                        held.append(gate)
            except TimeoutError:
                # 期限までに握れない: 書き込みの期限の超過にする（握った分は finally で放す）
                raise _deadline_exceeded(remaining, SOURCE_NEXT_STEP) from None
            record = current_record()
            if record is not None:
                record.add_lock_wait(time.monotonic() - waited_from)
            yield
        finally:
            # 握った逆の順に放す（取り消し・期限の超過でも、握った分だけ放す）
            for gate in reversed(held):
                gate.release()

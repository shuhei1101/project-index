"""文書の MCP・読み取り API と管理の MCP の専用の実行スロットと、稼働中の記録。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import contextvars
import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

# 文書の MCP・読み取り API の実行スロットの数（asyncio の既定の実行スロットと同じ本数）
DOCS_WORKERS = min(32, (os.cpu_count() or 1) + 4)
# 管理の MCP の実行スロットの数（長い処理 1 件と、その間の status・restart 1 件）
ADMIN_WORKERS = 2
# 実行中・待ち中の数と RSS を記録する間隔の秒数
RUNTIME_RECORD_INTERVAL_SEC = 60

__all__ = [
    "ADMIN_WORKERS",
    "DOCS_WORKERS",
    "RUNTIME_RECORD_INTERVAL_SEC",
    "ExecutionSlots",
    "RequestRecord",
    "current_record",
    "read_rss_mb",
    "record_periodically",
]


@dataclass(slots=True)
class RequestRecord:
    """1 回の要求の待ち・処理の時間と、要求の中でたどったファイルのキャッシュの件数。"""

    tool: str
    source: str | None = None
    # 実行スロットに入れてから動き始めるまでの秒数の合計
    slot_wait: float = 0.0
    # ワークツリーごとの排他を待った秒数の合計
    lock_wait: float = 0.0
    # 実行スロットで動き始めてから終わるまでの秒数の合計
    elapsed: float = 0.0
    # 捨てるかを判定するためにたどったファイルのキャッシュのキーの数の合計
    scanned: int = 0

    def add_lock_wait(self, seconds: float) -> None:
        """排他を待った秒数を足す。"""
        self.lock_wait += seconds

    def add_scanned(self, count: int) -> None:
        """たどったキャッシュのキーの数を足す。"""
        self.scanned += count


_current: contextvars.ContextVar[RequestRecord | None] = contextvars.ContextVar(
    "project_index_request_record", default=None
)


def current_record() -> RequestRecord | None:
    """今の文脈の要求の記録を返す。要求の外なら None。"""
    return _current.get()


_JobState = Literal["waiting", "running", "cancelled"]


class _Job:
    """実行スロットに入れた 1 つの仕事の状態（ExecutionSlots._guard の中で読み書きする）。"""

    __slots__ = ("state",)

    def __init__(self) -> None:
        self.state: _JobState = "waiting"


class ExecutionSlots:
    """文書の MCP・読み取り API と管理の MCP の要求の処理を、それぞれの専用の実行スロットで動かす。

    asyncio の既定の実行スロット（`asyncio.to_thread`）のスレッドは、停止のときに
    `asyncio.Runner.close` が終わりを最大 300 秒待つため使用しない。
    """

    def __init__(self, *, clock: Callable[[], float] = time.perf_counter) -> None:
        self.docs_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=DOCS_WORKERS, thread_name_prefix="docs"
        )
        self.admin_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=ADMIN_WORKERS, thread_name_prefix="admin"
        )
        self.clock = clock
        # 文書の MCP の実行スロットで動いている数と、入れて動き始めていない数（_guard で読み書きする）
        self._running = 0
        self._waiting = 0
        self._guard = threading.Lock()

    def counts(self) -> tuple[int, int]:
        """文書の MCP の実行スロットの (実行中の数, 待ち中の数) を返す。"""
        with self._guard:
            return self._running, self._waiting

    @contextlib.contextmanager
    def request(self, tool: str, *, source: str | None = None) -> Iterator[RequestRecord]:
        """1 回の要求の間、要求の記録を今の文脈に置き、抜けるときに 1 行でログに残す。"""
        record = RequestRecord(tool, source)
        token = _current.set(record)
        outcome = "ok"
        try:
            yield record
        except asyncio.CancelledError:
            # 呼び出し元の取り消し・切断
            outcome = "cancelled"
            raise
        except BaseException:
            outcome = "error"
            raise
        finally:
            logger.info(
                "要求を処理した（tool=%s source=%s slot_wait=%.3f lock_wait=%.3f elapsed=%.3f "
                "scanned=%d outcome=%s）",
                record.tool,
                record.source,
                record.slot_wait,
                record.lock_wait,
                record.elapsed,
                record.scanned,
                outcome,
            )
            _current.reset(token)

    async def run_docs[T](self, func: Callable[..., T], *args: object) -> T:
        """関数を文書の MCP の実行スロットで動かし、今の要求の記録に待ちと処理の時間を足す。"""
        job = _Job()
        queued_at = self.clock()
        with self._guard:
            self._waiting += 1
        context = contextvars.copy_context()

        def _work() -> T:
            started_at = self.clock()
            with self._guard:
                # 取り消し済みなら、待ち中の数は取り消した側が戻している
                if job.state == "waiting":
                    self._waiting -= 1
                job.state = "running"
                self._running += 1
            try:
                return func(*args)
            finally:
                finished_at = self.clock()
                with self._guard:
                    self._running -= 1
                record = current_record()
                if record is not None:
                    record.slot_wait += started_at - queued_at
                    record.elapsed += finished_at - started_at

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(self.docs_executor, context.run, _work)
        except asyncio.CancelledError:
            with self._guard:
                # 動き始める前の取り消し: ThreadPoolExecutor は仕事を呼ばないため、ここで戻す
                if job.state == "waiting":
                    self._waiting -= 1
                    job.state = "cancelled"
            raise

    async def run_admin[T](self, func: Callable[..., T], *args: object) -> T:
        """関数を管理の MCP の実行スロットで動かす。"""
        context = contextvars.copy_context()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.admin_executor, context.run, func, *args)


def read_rss_mb() -> int | None:
    """今のプロセスの RSS を MB で返す。読めなければ None。"""
    try:
        with open("/proc/self/statm", encoding="ascii") as statm:
            pages = int(statm.read().split()[1])
    except OSError, ValueError, IndexError:
        return None
    return pages * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024)


async def record_periodically(
    slots: ExecutionSlots,
    *,
    interval: float = RUNTIME_RECORD_INTERVAL_SEC,
    read_rss: Callable[[], int | None] = read_rss_mb,
) -> None:
    """実行中・待ち中の数と RSS を、間隔ごとに 1 行でログに残し続ける。"""
    while True:
        await asyncio.sleep(interval)
        running, waiting = slots.counts()
        logger.info("稼働中の記録（running=%d waiting=%d rss_mb=%s）", running, waiting, read_rss())

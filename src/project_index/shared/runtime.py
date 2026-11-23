"""文書の MCP・読み取り API・管理の MCP・書き込みの後の通知の判定の専用の実行スロットと、稼働中の記録。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import contextvars
import functools
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Sequence

logger = logging.getLogger(__name__)

# 文書の MCP・読み取り API の実行スロットの数（asyncio の既定の実行スロットと同じ本数）
DOCS_WORKERS = min(32, (os.cpu_count() or 1) + 4)
# 管理の MCP の実行スロットの数（長い処理 1 件と、その間の status・restart 1 件）
ADMIN_WORKERS = 2
# 書き込みの後の通知の判定の実行スロットの数（3 秒の間に届く要求の最大 3 件 × 1.2 を切り上げ）
POST_WRITE_WORKERS = 4
# 実行中・待ち中の数と RSS を記録する間隔の秒数
RUNTIME_RECORD_INTERVAL_SEC = 60

__all__ = [
    "ADMIN_WORKERS",
    "DOCS_WORKERS",
    "POST_WRITE_WORKERS",
    "RUNTIME_RECORD_INTERVAL_SEC",
    "ExecutionSlots",
    "Executor",
    "RequestRecord",
    "RequestState",
    "RunningRequest",
    "current_record",
    "read_rss_mb",
    "record_periodically",
]


Executor = Literal["docs", "post_write"]
RequestState = Literal["waiting", "running"]


@dataclass(slots=True)
class RequestRecord:
    """1 回の要求の待ち・処理の時間と、要求の中でたどったファイルのキャッシュの件数。"""

    tool: str
    # 要求が指す配信元の ID の並び（指さないときは空）
    sources: list[str] = field(default_factory=list[str])
    # 要求を動かす実行スロット
    executor: Executor = "docs"
    # 実行スロットで関数を動かしている間は running
    state: RequestState = "waiting"
    # request に入った時刻（ExecutionSlots.clock の値）
    received_at: float = 0.0
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


@dataclass(frozen=True, slots=True)
class RunningRequest:
    """状態の取得が返却する、終わっていない要求 1 件のコピー。"""

    tool: str
    sources: list[str]
    executor: Executor
    state: RequestState
    seconds: float


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
        self.post_write_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=POST_WRITE_WORKERS, thread_name_prefix="post_write"
        )
        self.clock = clock
        # 文書の MCP の実行スロットで動いている数と、入れて動き始めていない数（_guard で読み書きする）
        self._running = 0
        self._waiting = 0
        # 書き込みの後の通知の判定の実行スロットに入れて、終わっていない仕事の数（_guard で読み書きする）
        self._post_write_busy = 0
        # request の範囲に入っている要求の記録（キーは id(record)。_guard で読み書きする）
        self._requests: dict[int, RequestRecord] = {}
        self._guard = threading.Lock()

    def counts(self) -> tuple[int, int]:
        """文書の MCP の実行スロットの (実行中の数, 待ち中の数) を返す。"""
        with self._guard:
            return self._running, self._waiting

    def running(self) -> list[RunningRequest]:
        """request の範囲に入っている要求のコピーを、経過秒の長い順に返す。"""
        with self._guard:
            records = list(self._requests.values())
        now = self.clock()
        items = [
            RunningRequest(
                tool=record.tool,
                sources=list(record.sources),
                executor=record.executor,
                state=record.state,
                seconds=now - record.received_at,
            )
            for record in records
        ]
        return sorted(items, key=lambda item: item.seconds, reverse=True)

    @contextlib.contextmanager
    def request(
        self, tool: str, *, sources: Sequence[str] = (), executor: Executor = "docs"
    ) -> Generator[RequestRecord]:
        """1 回の要求の間、要求の記録を今の文脈と終わっていない要求の記録に置き、抜けるときに 1 行でログに残す。"""
        record = RequestRecord(tool, list(sources), executor, received_at=self.clock())
        token = _current.set(record)
        with self._guard:
            self._requests[id(record)] = record
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
                "要求を処理した（tool=%s source=%s executor=%s slot_wait=%.3f lock_wait=%.3f "
                "elapsed=%.3f scanned=%d outcome=%s）",
                record.tool,
                ",".join(record.sources) or None,
                record.executor,
                record.slot_wait,
                record.lock_wait,
                record.elapsed,
                record.scanned,
                outcome,
            )
            with self._guard:
                self._requests.pop(id(record), None)
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
            record = current_record()
            if record is not None:
                record.state = "running"
            try:
                return func(*args)
            finally:
                finished_at = self.clock()
                with self._guard:
                    self._running -= 1
                if record is not None:
                    record.state = "waiting"
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

    async def try_run_post_write[T](self, func: Callable[..., T], *args: object) -> T | None:
        """関数を書き込みの後の通知の判定の実行スロットで動かす。全て使用中なら動かさずに None を返す。"""
        job = _Job()
        with self._guard:
            if self._post_write_busy >= POST_WRITE_WORKERS:
                return None
            self._post_write_busy += 1
        queued_at = self.clock()
        context = contextvars.copy_context()

        def _work() -> T:
            started_at = self.clock()
            with self._guard:
                job.state = "running"
            record = current_record()
            if record is not None:
                record.state = "running"
            try:
                return func(*args)
            finally:
                finished_at = self.clock()
                with self._guard:
                    self._post_write_busy -= 1
                if record is not None:
                    record.state = "waiting"
                    record.slot_wait += started_at - queued_at
                    record.elapsed += finished_at - started_at

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(self.post_write_executor, context.run, _work)
        except asyncio.CancelledError:
            with self._guard:
                # 動き始める前の取り消し: ThreadPoolExecutor は仕事を呼ばないため、ここで戻す
                if job.state == "waiting":
                    self._post_write_busy -= 1
                    job.state = "cancelled"
            raise

    async def run_admin[T](self, func: Callable[..., T], *args: object) -> T:
        """関数を管理の MCP の実行スロットで動かす。"""
        context = contextvars.copy_context()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.admin_executor, context.run, functools.partial(func, *args)
        )


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

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

import pytest

from project_index.shared import runtime
from project_index.shared.runtime import (
    DOCS_WORKERS,
    ExecutionSlots,
    current_record,
    read_rss_mb,
    record_periodically,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def _add_scanned(count: int) -> Callable[[], None]:
    """今の要求の記録にキャッシュの件数を足す関数を返す。"""

    def _run() -> None:
        record = current_record()
        assert record is not None
        record.add_scanned(count)

    return _run


def _blocker(gate: threading.Event, started: threading.Semaphore) -> Callable[[], None]:
    """動き始めを知らせてから、`gate` が放されるまで止まる関数を返す。"""

    def _run() -> None:
        started.release()
        gate.wait(timeout=10)

    return _run


async def _fill_docs(slots: ExecutionSlots, gate: threading.Event) -> list[asyncio.Task[None]]:
    """文書の MCP の実行スロットを `DOCS_WORKERS` 本の止まった仕事で埋める。"""
    started = threading.Semaphore(0)
    tasks = [
        asyncio.create_task(slots.run_docs(_blocker(gate, started))) for _ in range(DOCS_WORKERS)
    ]
    # 全ての仕事が実行スロットのスレッドで動き始めるまで待つ
    for _ in range(DOCS_WORKERS):
        await asyncio.to_thread(started.acquire, True, 10)
    return tasks


def _record_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """要求を処理した記録の行の本文を返す。"""
    return [r.getMessage() for r in caplog.records if "要求を処理した" in r.getMessage()]


def _periodic_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """稼働中の記録の行の本文を返す。"""
    return [r.getMessage() for r in caplog.records if "稼働中の記録" in r.getMessage()]


def test_execution_slots_request(caplog: pytest.LogCaptureFixture) -> None:
    """1 要求で run_docs を 2 回呼んでも 1 行（正常系）。"""
    # 準備
    caplog.set_level(logging.INFO)
    slots = ExecutionSlots()

    async def scenario() -> None:
        with slots.request("search_docs", sources=["sample"]):
            await slots.run_docs(_add_scanned(2))
            await slots.run_docs(_add_scanned(3))

    # 実行
    asyncio.run(scenario())
    # 検証
    lines = _record_lines(caplog)
    assert len(lines) == 1
    assert "search_docs" in lines[0]
    assert "sample" in lines[0]
    assert "docs" in lines[0]
    assert "scanned=5" in lines[0]
    assert "ok" in lines[0]


def test_execution_slots_request_when_cancelled(caplog: pytest.LogCaptureFixture) -> None:
    """取り消しも 1 行残す（異常系）。"""
    # 準備
    caplog.set_level(logging.INFO)
    slots = ExecutionSlots()

    async def inside() -> None:
        with slots.request("search_docs"):
            await asyncio.sleep(10)

    async def scenario() -> None:
        task = asyncio.create_task(inside())
        await asyncio.sleep(0.01)
        task.cancel()
        await task

    # 実行・検証
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scenario())
    lines = _record_lines(caplog)
    assert len(lines) == 1
    assert "cancelled" in lines[0]
    assert slots.running() == []


def test_execution_slots_run_docs() -> None:
    """戻り値と記録への足し込み（正常系）。"""
    # 準備
    slots = ExecutionSlots()

    async def scenario() -> tuple[str, float]:
        with slots.request("search_docs") as record:
            value = await slots.run_docs(lambda: "ok")
        return value, record.elapsed

    # 実行
    value, elapsed = asyncio.run(scenario())
    # 検証
    assert value == "ok"
    assert elapsed >= 0.0
    assert slots.counts() == (0, 0)


def test_execution_slots_run_docs_when_raised() -> None:
    """例外でも数を戻す（異常系）。"""
    # 準備
    slots = ExecutionSlots()

    def fail() -> None:
        message = "boom"
        raise RuntimeError(message)

    # 実行・検証
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(slots.run_docs(fail))
    assert slots.counts() == (0, 0)


def test_execution_slots_run_docs_when_full() -> None:
    """埋まっている間は待ち中に数える（正常系）。"""
    # 準備
    slots = ExecutionSlots()
    gate = threading.Event()

    async def scenario() -> tuple[tuple[int, int], float]:
        blockers = await _fill_docs(slots, gate)
        with slots.request("search_docs") as record:
            extra = asyncio.create_task(slots.run_docs(lambda: None))
            await asyncio.sleep(0.05)
            during = slots.counts()
            gate.set()
            await extra
        await asyncio.gather(*blockers)
        return during, record.slot_wait

    # 実行
    during, slot_wait = asyncio.run(scenario())
    # 検証
    assert during == (DOCS_WORKERS, 1)
    assert slot_wait > 0.0


def test_execution_slots_run_docs_when_cancelled_while_waiting(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """動き始める前の取り消しで待ち中の数を戻す（異常系）。"""
    # 準備
    caplog.set_level(logging.INFO)
    slots = ExecutionSlots()
    gate = threading.Event()
    called: list[bool] = []

    async def waiting() -> None:
        with slots.request("search_docs"):
            await slots.run_docs(lambda: called.append(True))

    async def scenario() -> tuple[tuple[int, int], tuple[int, int]]:
        blockers = await _fill_docs(slots, gate)
        task = asyncio.create_task(waiting())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        after_cancel = slots.counts()
        gate.set()
        await asyncio.gather(*blockers)
        return after_cancel, slots.counts()

    # 実行
    after_cancel, after_release = asyncio.run(scenario())
    # 検証
    assert after_cancel == (DOCS_WORKERS, 0)
    assert after_release == (0, 0)
    assert called == []
    assert "cancelled" in _record_lines(caplog)[0]


def test_execution_slots_run_admin_when_docs_full() -> None:
    """文書の MCP の実行スロットが埋まっていても動く（正常系）。"""
    # 準備
    slots = ExecutionSlots()
    gate = threading.Event()

    async def scenario() -> tuple[str, bool]:
        blockers = await _fill_docs(slots, gate)
        async with asyncio.timeout(5):
            value = await slots.run_admin(lambda: "admin")
        released_before = gate.is_set()
        gate.set()
        await asyncio.gather(*blockers)
        return value, released_before

    # 実行
    value, released_before = asyncio.run(scenario())
    # 検証
    assert value == "admin"
    assert released_before is False


def test_execution_slots_try_run_post_write() -> None:
    """空いていれば動かして戻り値を返す（正常系）。"""
    # 準備
    slots = ExecutionSlots()

    async def scenario() -> tuple[str | None, float]:
        with slots.request("post_write", executor="post_write") as record:
            value = await slots.try_run_post_write(lambda: "ok")
        return value, record.elapsed

    # 実行
    value, elapsed = asyncio.run(scenario())
    # 検証
    assert value == "ok"
    assert elapsed >= 0.0


def test_execution_slots_try_run_post_write_when_full() -> None:
    """全て使用中なら動かさずに None（正常系）。"""
    # 準備
    slots = ExecutionSlots()
    gate = threading.Event()
    started = threading.Semaphore(0)
    called: list[bool] = []

    async def scenario() -> tuple[str | None, str | None]:
        blockers = [
            asyncio.create_task(slots.try_run_post_write(_blocker(gate, started)))
            for _ in range(runtime.POST_WRITE_WORKERS)
        ]
        for _ in range(runtime.POST_WRITE_WORKERS):
            await asyncio.to_thread(started.acquire, True, 10)
        async with asyncio.timeout(5):
            during = await slots.try_run_post_write(lambda: called.append(True) or "extra")
        gate.set()
        await asyncio.gather(*blockers)
        after = await slots.try_run_post_write(lambda: "after")
        return during, after

    # 実行
    during, after = asyncio.run(scenario())
    # 検証
    assert during is None
    assert called == []
    assert after == "after"


def test_execution_slots_try_run_post_write_when_docs_full() -> None:
    """文書の MCP の実行スロットが埋まっていても動く（正常系）。"""
    # 準備
    slots = ExecutionSlots()
    gate = threading.Event()

    async def scenario() -> tuple[str | None, bool]:
        blockers = await _fill_docs(slots, gate)
        async with asyncio.timeout(5):
            value = await slots.try_run_post_write(lambda: "ok")
        released_before = gate.is_set()
        gate.set()
        await asyncio.gather(*blockers)
        return value, released_before

    # 実行
    value, released_before = asyncio.run(scenario())
    # 検証
    assert value == "ok"
    assert released_before is False


def test_execution_slots_running() -> None:
    """範囲の中の要求だけを長い順に返す（正常系）。"""
    # 準備
    now = [100.0]
    slots = ExecutionSlots(clock=lambda: now[0])

    # 実行
    with slots.request("write_docs", sources=["a"]):
        now[0] += 10
        with slots.request("search_docs"):
            now[0] += 1
            inside = slots.running()
    after = slots.running()
    # 検証
    assert [(r.tool, r.sources, r.executor, r.state, r.seconds) for r in inside] == [
        ("write_docs", ["a"], "docs", "waiting", 11.0),
        ("search_docs", [], "docs", "waiting", 1.0),
    ]
    assert after == []


def test_current_record_when_outside() -> None:
    """要求の外では None（正常系）。"""
    # 準備・実行
    record = current_record()
    # 検証
    assert record is None


def test_read_rss_mb() -> None:
    """Linux では正の値（正常系）。"""
    # 準備・実行
    rss = read_rss_mb()
    # 検証
    assert rss is not None
    assert rss > 0


def test_record_periodically(caplog: pytest.LogCaptureFixture) -> None:
    """間隔ごとに 1 行（正常系）。"""
    # 準備
    caplog.set_level(logging.INFO)
    slots = ExecutionSlots()

    async def scenario() -> None:
        task = asyncio.create_task(record_periodically(slots, interval=0.01, read_rss=lambda: 100))
        # 間隔の 20 倍の間動かしてから取り消す
        await asyncio.sleep(0.2)
        task.cancel()
        await task

    # 実行・検証
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scenario())
    lines = _periodic_lines(caplog)
    assert "100" in lines[0]
    assert "running=0" in lines[0]
    assert "waiting=0" in lines[0]

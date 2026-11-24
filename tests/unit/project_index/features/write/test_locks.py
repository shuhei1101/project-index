from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from project_index.features.write.locks import (
    RepositoryLocks,
    SourceLocks,
    WriteGates,
    WriteLockKeys,
)
from project_index.shared.deadline import Deadline
from project_index.shared.errors import WriteDeadlineExceededError


def test_source_locks_hold() -> None:
    """同じ配信元は待つ（正常系）。"""
    # 準備
    locks = SourceLocks()
    holder_entered = threading.Event()
    log: list[str] = []

    def hold_source_a() -> None:
        with locks.hold("a"):
            holder_entered.set()
            time.sleep(0.2)
            log.append("a-done")

    holder = threading.Thread(target=hold_source_a)
    holder.start()
    holder_entered.wait(timeout=5)
    # 実行
    with locks.hold("b"):
        log.append("b-in")
    with locks.hold("a"):
        log.append("a-second-in")
    holder.join(timeout=5)
    # 検証
    assert log == ["b-in", "a-done", "a-second-in"]


def test_source_locks_hold_when_timeout() -> None:
    """待ち時間の上限を超える（異常系）。"""
    # 準備
    locks = SourceLocks()
    holder_entered = threading.Event()
    release = threading.Event()

    def hold_source() -> None:
        with locks.hold("a"):
            holder_entered.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_source)
    holder.start()
    holder_entered.wait(timeout=5)
    # 実行・検証
    with pytest.raises(WriteDeadlineExceededError), locks.hold("a", timeout=0.1):
        pass
    release.set()
    holder.join(timeout=5)


def test_repository_locks_hold() -> None:
    """同じリポジトリは待つ（正常系）。"""
    # 準備
    locks = RepositoryLocks()
    holder_entered = threading.Event()
    log: list[str] = []

    def hold_repo_a() -> None:
        with locks.hold(Path("/repo/a/.git")):
            holder_entered.set()
            time.sleep(0.2)
            log.append("a-done")

    holder = threading.Thread(target=hold_repo_a)
    holder.start()
    holder_entered.wait(timeout=5)
    # 実行
    with locks.hold(Path("/repo/b/.git")):
        log.append("b-in")
    with locks.hold(Path("/repo/a/.git")):
        log.append("a-second-in")
    holder.join(timeout=5)
    # 検証
    assert log == ["b-in", "a-done", "a-second-in"]


def test_repository_locks_hold_when_timeout() -> None:
    """待ち時間の上限を超える（異常系）。"""
    # 準備
    locks = RepositoryLocks()
    holder_entered = threading.Event()
    release = threading.Event()

    def hold_repo() -> None:
        with locks.hold(Path("/repo/a/.git")):
            holder_entered.set()
            release.wait(timeout=5)

    holder = threading.Thread(target=hold_repo)
    holder.start()
    holder_entered.wait(timeout=5)
    # 実行・検証
    with pytest.raises(WriteDeadlineExceededError), locks.hold(Path("/repo/a/.git"), timeout=0.1):
        pass
    release.set()
    holder.join(timeout=5)


def _deadline(limit_sec: float) -> Deadline:
    """今から limit_sec 秒後の期限。"""
    return Deadline(limit_sec=limit_sec, started=time.monotonic())


def test_write_gates_hold() -> None:
    """同じ配信元は待ち、別の配信元は待たない（正常系）。"""
    # 準備
    gates = WriteGates()
    log: list[str] = []

    async def scenario() -> None:
        entered = asyncio.Event()

        async def task_a() -> None:
            async with gates.hold(WriteLockKeys(repo=None, source_id="s1"), _deadline(5)):
                entered.set()
                await asyncio.sleep(0.2)
                log.append("a-done")

        async def task_b() -> None:
            async with gates.hold(WriteLockKeys(repo=None, source_id="s1"), _deadline(5)):
                log.append("b-in")

        async def task_c() -> None:
            async with gates.hold(WriteLockKeys(repo=None, source_id="s2"), _deadline(5)):
                log.append("c-in")

        async with asyncio.TaskGroup() as group:
            group.create_task(task_a())
            await entered.wait()
            group.create_task(task_b())
            group.create_task(task_c())

    # 実行
    asyncio.run(scenario())
    # 検証
    assert log == ["c-in", "a-done", "b-in"]


def test_write_gates_hold_when_repo() -> None:
    """同じリポジトリは配信元が違っても待つ（正常系）。"""
    # 準備
    gates = WriteGates()
    repo = Path("/repo/r1/.git")
    log: list[str] = []

    async def scenario() -> None:
        entered = asyncio.Event()

        async def task_a() -> None:
            async with gates.hold(WriteLockKeys(repo=repo, source_id="s1"), _deadline(5)):
                entered.set()
                await asyncio.sleep(0.2)
                log.append("a-done")

        async def task_b() -> None:
            async with gates.hold(WriteLockKeys(repo=repo, source_id="s2"), _deadline(5)):
                log.append("b-in")

        async with asyncio.TaskGroup() as group:
            group.create_task(task_a())
            await entered.wait()
            group.create_task(task_b())

    # 実行
    asyncio.run(scenario())
    # 検証
    assert log == ["a-done", "b-in"]


def test_write_gates_hold_when_deadline() -> None:
    """期限までに握れない（異常系）。"""
    # 準備
    gates = WriteGates()
    keys = WriteLockKeys(repo=None, source_id="s1")
    log: list[str] = []

    async def scenario() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()

        async def task_a() -> None:
            async with gates.hold(keys, _deadline(5)):
                entered.set()
                await release.wait()

        async def task_b() -> None:
            with pytest.raises(WriteDeadlineExceededError):
                async with gates.hold(keys, _deadline(0.1)):
                    log.append("b-in")
            log.append("b-timeout")
            release.set()

        async with asyncio.TaskGroup() as group:
            group.create_task(task_a())
            await entered.wait()
            group.create_task(task_b())
        async with gates.hold(keys, _deadline(0.1)):
            log.append("after-in")

    # 実行
    asyncio.run(scenario())
    # 検証
    assert log == ["b-timeout", "after-in"]

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from project_index.features.write.locks import RepositoryLocks, SourceLocks
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

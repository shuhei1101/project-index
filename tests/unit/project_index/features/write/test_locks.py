from __future__ import annotations

import threading
import time

from project_index.features.write.locks import SourceLocks


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

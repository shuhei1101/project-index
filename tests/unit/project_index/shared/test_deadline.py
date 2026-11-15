from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from project_index.shared.deadline import Deadline
from project_index.shared.errors import WriteDeadlineExceededError

if TYPE_CHECKING:
    from collections.abc import Callable


def _clock(now: float) -> Callable[[], float]:
    """いつも `now` を返す時計。"""
    return lambda: now


def test_deadline_remaining() -> None:
    """期限の前（正常系）。"""
    # 準備
    deadline = Deadline(limit_sec=32, started=10, clock=_clock(20))
    # 実行
    result = deadline.remaining()
    # 検証
    assert result == 22


def test_deadline_remaining_when_passed() -> None:
    """期限の後（正常系）。"""
    # 準備
    deadline = Deadline(limit_sec=32, started=10, clock=_clock(50))
    # 実行
    result = deadline.remaining()
    # 検証
    assert result == 0


def test_deadline_cap() -> None:
    """残りの時間で切る（正常系）。"""
    # 準備
    deadline = Deadline(limit_sec=32, started=10, clock=_clock(20))
    # 実行
    long_cap = deadline.cap(30)
    short_cap = deadline.cap(5)
    # 検証
    assert long_cap == 22
    assert short_cap == 5


def test_deadline_check() -> None:
    """期限の前は送らない（正常系）。"""
    # 準備
    deadline = Deadline(limit_sec=32, started=10, clock=_clock(20))
    # 実行・検証
    deadline.check()


def test_deadline_check_when_passed() -> None:
    """期限の後（異常系）。"""
    # 準備
    deadline = Deadline(limit_sec=32, started=10, clock=_clock(43))
    # 実行・検証
    with pytest.raises(WriteDeadlineExceededError, match="書き込みの期限") as exc_info:
        deadline.check()
    assert exc_info.value.deadline_sec == 32
    assert exc_info.value.elapsed_sec == 33

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from project_index.shared.background import BackgroundGate

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class _FakeClock:
    """進める秒数をテストが決める時計。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _gate() -> tuple[BackgroundGate, _FakeClock, list[float]]:
    """偽物の時計と、渡された秒数を記録する休みを持つ関所を返す。"""
    clock = _FakeClock()
    slept: list[float] = []
    return BackgroundGate(clock=clock, sleep=slept.append), clock, slept


def _run_in_thread(target: Callable[[], None]) -> None:
    """別のスレッドで `target` を実行し、終わるまで待つ。"""
    thread = threading.Thread(target=target)
    thread.start()
    thread.join(timeout=10)


def test_background_gate_foreground() -> None:
    """応答中の間だけ active（正常系）。"""
    # 準備
    gate, _, _ = _gate()
    # 実行
    with gate.foreground():
        with gate.foreground():
            pass
        inner_left = gate.active
    outer_left = gate.active
    # 検証
    assert inner_left is True
    assert outer_left is False


def test_background_gate_foreground_when_raised() -> None:
    """例外で抜けても数を戻す（異常系）。"""
    # 準備
    gate, _, _ = _gate()
    # 実行・検証
    message = "boom"
    with pytest.raises(RuntimeError, match="boom"), gate.foreground():
        raise RuntimeError(message)
    assert gate.active is False


def test_background_gate_unit_when_foreground_active() -> None:
    """応答中は 1 件の時間の 9 倍だけ休む（正常系）。"""
    # 準備
    gate, clock, slept = _gate()

    def work() -> None:
        with gate.background(), gate.unit():
            clock.advance(1.0)

    # 実行
    with gate.foreground():
        _run_in_thread(work)
    # 検証
    assert slept == [pytest.approx(9.0)]


def test_background_gate_unit_when_idle() -> None:
    """応答中でなければ休まない（正常系）。"""
    # 準備
    gate, clock, slept = _gate()

    def work() -> None:
        with gate.background(), gate.unit():
            clock.advance(1.0)

    # 実行
    _run_in_thread(work)
    # 検証
    assert slept == []


def test_background_gate_unit_when_not_background() -> None:
    """裏の処理のスレッドでなければ何もしない（正常系）。"""
    # 準備
    gate, clock, slept = _gate()
    ran: list[bool] = []
    # 実行
    with gate.foreground(), gate.unit():
        clock.advance(1.0)
        ran.append(True)
    # 検証
    assert ran == [True]
    assert slept == []


def test_background_gate_unit_when_nested() -> None:
    """入れ子の 1 件では一番外だけ休む（正常系）。"""
    # 準備
    gate, clock, slept = _gate()

    def work() -> None:
        with gate.background(), gate.unit(), gate.unit():
            clock.advance(1.0)

    # 実行
    with gate.foreground():
        _run_in_thread(work)
    # 検証
    assert slept == [pytest.approx(9.0)]


def _count_concurrent(gate: BackgroundGate, times: int) -> list[int]:
    """2 つのスレッドで `unit` を `times` 回ずつ実行し、実行中の数を 1 件ごとに記録した並びを返す。"""
    running = 0
    seen: list[int] = []
    lock = threading.Lock()

    def work() -> None:
        nonlocal running
        with gate.background():
            for _ in range(times):
                with gate.unit():
                    with lock:
                        running += 1
                        seen.append(running)
                    threading.Event().wait(0.001)
                    with lock:
                        running -= 1

    threads = [threading.Thread(target=work) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return seen


def test_background_gate_unit_when_concurrent() -> None:
    """2 本の裏の処理の 1 件が重ならない（正常系）。"""
    # 準備
    gate = BackgroundGate()
    # 実行
    seen = _count_concurrent(gate, 20)
    # 検証
    assert len(seen) == 40
    assert max(seen) == 1


def _three_items(clock: _FakeClock) -> Iterator[str]:
    """要素を作るたびに時計を 0.5 秒進めて a・b・c を返すジェネレータ。"""
    for item in ("a", "b", "c"):
        clock.advance(0.5)
        yield item


def test_background_gate_each_when_foreground_active() -> None:
    """要素ごとに休む（正常系）。"""
    # 準備
    gate, clock, slept = _gate()
    items: list[str] = []

    def work() -> None:
        with gate.background():
            for item in gate.each(_three_items(clock)):
                clock.advance(0.5)
                items.append(item)

    # 実行
    with gate.foreground():
        _run_in_thread(work)
    # 検証
    assert items == ["a", "b", "c"]
    assert slept == [pytest.approx(9.0), pytest.approx(9.0), pytest.approx(9.0)]


def test_background_gate_yield_unit_when_idle() -> None:
    """応答中でなければ 2 本の 1 件が重なって進む（正常系）。"""
    # 準備
    gate, _, slept = _gate()
    both_inside = threading.Barrier(2, timeout=5)
    finished: list[str] = []

    def work(name: str) -> None:
        with gate.background(), gate.yield_unit():
            both_inside.wait()
            finished.append(name)

    threads = [threading.Thread(target=work, args=(name,)) for name in ("x", "y")]
    # 実行
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    # 検証
    assert sorted(finished) == ["x", "y"]
    assert slept == []


def test_background_gate_yield_unit_when_foreground_active() -> None:
    """応答中は 1 件ずつにして休む（正常系）。"""
    # 準備
    gate, clock, slept = _gate()
    running = 0
    seen: list[int] = []
    lock = threading.Lock()

    def work() -> None:
        nonlocal running
        with gate.background():
            for _ in range(3):
                with gate.yield_unit():
                    with lock:
                        running += 1
                        seen.append(running)
                        clock.advance(1.0)
                    threading.Event().wait(0.001)
                    with lock:
                        running -= 1

    threads = [threading.Thread(target=work) for _ in range(2)]
    # 実行
    with gate.foreground():
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
    # 検証
    assert max(seen) == 1
    assert slept == [pytest.approx(9.0)] * 6

"""PoC 専用: 区間ごとの経過時間とスレッドの CPU 時間を JSON 行で記録する。"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

# 記録の先。未設定なら何も書かない
_PATH = os.environ.get("POC_TIMING_LOG")
_LOCK = threading.Lock()


def flag(name: str) -> bool:
    """PoC の切り替えの環境変数が `1` かを返す。"""
    return os.environ.get(name) == "1"


def number(name: str) -> float | None:
    """PoC の切り替えの環境変数の数値を返す（無ければ `None`）。"""
    value = os.environ.get(name)
    return None if not value else float(value)


def emit(event: str, **fields: Any) -> None:
    """1 行を書く。"""
    if _PATH is None:
        return
    row = {"t": time.time(), "thread": threading.current_thread().name, "event": event, **fields}
    line = json.dumps(row, ensure_ascii=False, default=str)
    with _LOCK, open(_PATH, "a", encoding="utf-8") as file:
        file.write(line + "\n")


@contextlib.contextmanager
def span(event: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """区間の終わりに、開始の時刻・経過時間・スレッドの CPU 時間を 1 行で書く。"""
    start = time.time()
    wall0 = time.perf_counter()
    cpu0 = time.thread_time()
    extra: dict[str, Any] = {}
    try:
        yield extra
    finally:
        emit(
            event,
            start=start,
            wall=time.perf_counter() - wall0,
            cpu=time.thread_time() - cpu0,
            **fields,
            **extra,
        )




def text(name: str) -> str | None:
    """PoC の切り替えの環境変数の文字列を返す（無ければ `None`）。"""
    return os.environ.get(name) or None


# 構成 4: 行の読み込みを関所で休ませるための、起動の部品と今のスレッドが読む行
GATE: Any = None
REGISTRY: Any = None
_ROW = threading.local()


def set_row(index: int | None) -> None:
    """今のスレッドが読み込む配信元の行の位置を記録する。"""
    _ROW.index = index


@contextlib.contextmanager
def row_unit() -> Iterator[None]:
    """構成 4: 要求が待っていない行の読み込みの 1 件を、関所の裏の処理の 1 件にする。"""
    index = getattr(_ROW, "index", None)
    if not flag("POC_GATE_ROWS") or GATE is None or index is None:
        yield
        return
    # 待っている要求が指す行は休ませない
    if REGISTRY is not None and index in REGISTRY._requested:  # noqa: SLF001
        yield
        return
    with GATE.background(), GATE.unit():
        yield

"""要求の応答中に、裏の検査と書き出しが使用する時間を抑える関所。"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Iterator

# 要求の応答中に、裏の検査と書き出しが合わせて使用する時間の割合の上限
BACKGROUND_SHARE = 0.1

__all__ = ["BACKGROUND_SHARE", "BackgroundGate"]


class BackgroundGate:
    """要求の応答中は、裏の処理を 1 件ずつ順に進め、1 件の後に休ませて使用する時間を抑える。"""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.clock = clock
        self.sleep = sleep
        # 応答中の要求の数。_guard で読み書きする
        self._active = 0
        self._guard = threading.Lock()
        # 裏の処理の 1 件とその後の休みを、1 つのスレッドだけが行うための排他（入れ子の 1 件も通す）
        self._turn = threading.RLock()
        # スレッドごとの、裏の処理の深さと 1 件の入れ子の深さ
        self._local = threading.local()

    @property
    def active(self) -> bool:
        """応答中の要求があるかを返す。"""
        with self._guard:
            return self._active > 0

    @property
    def in_background(self) -> bool:
        """今のスレッドが裏の処理のスレッドかを返す。"""
        return getattr(self._local, "background", 0) > 0

    @property
    def in_unit(self) -> bool:
        """今のスレッドが裏の処理の 1 件の中かを返す。"""
        return getattr(self._local, "units", 0) > 0

    @contextlib.contextmanager
    def foreground(self) -> Generator[None]:
        """要求の処理の間、応答中の要求の数を 1 つ進める。"""
        with self._guard:
            self._active += 1
        try:
            yield
        finally:
            with self._guard:
                self._active -= 1

    @contextlib.contextmanager
    def background(self) -> Generator[None]:
        """このスレッドを、中にいる間だけ裏の処理のスレッドにする。"""
        self._local.background = getattr(self._local, "background", 0) + 1
        try:
            yield
        finally:
            self._local.background -= 1

    @contextlib.contextmanager
    def unit(self) -> Generator[None]:
        """裏の処理の 1 件を他の裏の処理と重ならずに実行し、応答中なら 1 件の後に休む。"""
        # 要求のスレッド: 何もせずに処理だけを実行する
        if not self.in_background:
            yield
            return
        with self._turn:
            depth = getattr(self._local, "units", 0)
            self._local.units = depth + 1
            started = self.clock()
            try:
                yield
            finally:
                self._local.units = depth
            # 入れ子の一番外の 1 件で、応答中の要求があれば、使用した時間の割合が上限になるまで休む
            if depth == 0 and self.active and not os.environ.get("PI_POC_GATE_NO_SLEEP"):  # PoC #237
                elapsed = self.clock() - started
                self.sleep(elapsed * (1 - BACKGROUND_SHARE) / BACKGROUND_SHARE)

    @contextlib.contextmanager
    def yield_unit(self) -> Generator[None]:
        """応答中だけ、裏の処理の 1 件を他の裏の処理と重ならずに実行して休む。応答中でなければ排他を取らずに実行する。"""
        # 応答中でない裏の処理のスレッド: 他の裏の処理と重なって進める
        if self.in_background and not self.active:
            yield
            return
        with self.unit():
            yield

    def each[T](self, items: Iterable[T]) -> Iterator[T]:
        """要素 1 つごとに、取り出しと呼び出し側の 1 回分の処理を裏の処理の 1 件にする。"""
        iterator = iter(items)
        with contextlib.suppress(_ExhaustedError):
            while True:
                with self.unit():
                    # 要素が尽きた 1 件は、例外で抜けて休まない
                    item = next(iterator, _END)
                    if item is _END:
                        raise _ExhaustedError
                    yield item  # type: ignore[misc]


class _ExhaustedError(Exception):
    """裏の処理の繰り返しの要素が尽きたことを、休まずに 1 件から抜けるために送る。"""


# 要素が尽きたことを表す印
_END = object()

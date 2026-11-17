"""配信元ごとの検査の結果。"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from project_index.features.documents.store import DocumentStore, check_sync
from project_index.features.documents.types import SyncReport
from project_index.features.read.nav import nav_warnings
from project_index.shared.background import BackgroundGate
from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from project_index.features.sources.types import ServedSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceCheck:
    """1 つの配信元の同期のずれと `nav` の警告。"""

    report: SyncReport
    nav: list[Violation]


class SourceChecks:
    """配信元の ID ごとに最後の検査の結果を持つ。"""

    def __init__(
        self,
        on_checked: Callable[[ServedSource, SourceCheck], None] | None = None,
        *,
        gate: BackgroundGate | None = None,
    ) -> None:
        # 結果を置き換えた検査ごとに呼ぶ（起動では警告のログを書く関数）
        self.on_checked = on_checked
        # 裏の検査のスレッドを裏の処理のスレッドにする関所
        self.gate = gate if gate is not None else BackgroundGate()
        self._lock = threading.Lock()
        self._results: dict[str, tuple[int, SourceCheck]] = {}
        # 配信元ごとの、始めた検査の数
        self._started: dict[str, int] = {}
        self._running: set[str] = set()
        # 裏で検査中に要求された配信元の ID → 最後に要求された配信元
        self._requested: dict[str, ServedSource] = {}
        # 裏の検査のスレッドが先頭から順に取り出す、検査を待つ配信元
        self._queue: deque[tuple[DocumentStore, ServedSource]] = deque()
        # 動いている裏の検査のスレッド（無ければ None）
        self._worker: threading.Thread | None = None

    @property
    def checking(self) -> bool:
        """裏で検査している配信元があるかを返す。"""
        with self._lock:
            return bool(self._running)

    def forget(self, source_ids: Iterable[str]) -> None:
        """渡した配信元の ID の結果を捨てる（始めた順の番号は残す）。"""
        with self._lock:
            for source_id in source_ids:
                self._results.pop(source_id, None)

    def refresh(self, store: DocumentStore, source: ServedSource) -> SourceCheck:
        """配信元を検査し、後に始めた検査の結果を上書きしないように持って返す。"""
        with self._lock:
            number = self._started.get(source.id, 0) + 1
            self._started[source.id] = number
        # 配信元のフォルダをたどる検査はロックの外で流す
        check = SourceCheck(report=check_sync(store, source), nav=nav_warnings(store, source))
        with self._lock:
            # 持っている結果より後に始めた検査のときだけ置き換える
            held = self._results.get(source.id)
            replaced = held is None or held[0] < number
            if replaced:
                self._results[source.id] = (number, check)
        if replaced and self.on_checked is not None:
            self.on_checked(source, check)
        return check

    def get(self, source_id: str) -> SourceCheck | None:
        """配信元の ID の最後の検査の結果を返す（まだ検査していなければ `None`）。"""
        with self._lock:
            held = self._results.get(source_id)
        return None if held is None else held[1]

    def refresh_later(
        self, store: DocumentStore, sources: list[ServedSource]
    ) -> list[threading.Thread]:
        """配信元を 1 本の裏のスレッドで順に検査し直し、待たずに戻る。"""
        with self._lock:
            for source in sources:
                # 検査を待つか検査中の配信元は、終えた後にもう 1 回流すよう要求だけを立てる
                if source.id in self._running:
                    self._requested[source.id] = source
                else:
                    self._running.add(source.id)
                    self._queue.append((store, source))
            # 裏の検査のスレッドが動いていれば、待っている配信元はそのスレッドが取り出す
            if self._worker is not None:
                return []
            worker = threading.Thread(
                target=self._work, name="project-index-source-checks", daemon=True
            )
            self._worker = worker
        worker.start()
        return [worker]

    def _work(self) -> None:
        """検査を待つ配信元が無くなるまで、先頭から順に検査する。"""
        with self.gate.background():
            while True:
                with self._lock:
                    # 待っている配信元が無い: スレッドを終える
                    if not self._queue:
                        self._worker = None
                        return
                    store, source = self._queue.popleft()
                try:
                    self.refresh(store, source)
                except Exception:
                    logger.exception("配信元の検査に失敗した（%s）", source.id)
                with self._lock:
                    # 検査中に要求があれば、要求された最新の配信元を末尾へ入れてもう 1 回検査する
                    if source.id in self._requested:
                        self._queue.append((store, self._requested.pop(source.id)))
                    else:
                        self._running.discard(source.id)

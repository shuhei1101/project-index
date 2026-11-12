"""配信元ごとの検査の結果。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from project_index.features.documents.store import DocumentStore, check_sync
from project_index.features.documents.types import SyncReport
from project_index.features.read.nav import nav_warnings
from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from project_index.features.sources.types import ServedSource

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceCheck:
    """1 つの配信元の同期のずれと `nav` の警告。"""

    report: SyncReport
    nav: list[Violation]


class SourceChecks:
    """配信元の ID ごとに最後の検査の結果を持つ。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: dict[str, tuple[int, SourceCheck]] = {}
        # 配信元ごとの、始めた検査の数
        self._started: dict[str, int] = {}
        self._running: set[str] = set()
        self._requested: set[str] = set()

    def refresh(self, store: DocumentStore, source: ServedSource) -> SourceCheck:
        """配信元を検査し、後に始めた検査の結果を上書きしないように持って返す。"""
        with self._lock:
            number = self._started.get(source.id, 0) + 1
            self._started[source.id] = number
        # 配信元のフォルダをたどる検査はロックの外で流す
        check = SourceCheck(report=check_sync(store, source), nav=nav_warnings(store, source))
        with self._lock:
            held = self._results.get(source.id)
            if held is None or held[0] < number:
                self._results[source.id] = (number, check)
        return check

    def get(self, source_id: str) -> SourceCheck | None:
        """配信元の ID の最後の検査の結果を返す（まだ検査していなければ `None`）。"""
        with self._lock:
            held = self._results.get(source_id)
        return None if held is None else held[1]

    def refresh_later(
        self, store: DocumentStore, sources: list[ServedSource]
    ) -> list[threading.Thread]:
        """裏で検査していない配信元を裏のスレッドで検査し直し、待たずに戻る。"""
        starting: list[ServedSource] = []
        with self._lock:
            for source in sources:
                # 検査中の配信元は、終えた後にもう 1 回流すよう要求だけを立てる
                if source.id in self._running:
                    self._requested.add(source.id)
                else:
                    self._running.add(source.id)
                    starting.append(source)
        threads = [
            threading.Thread(
                target=self._work,
                args=(store, source),
                name=f"project-index-source-checks-{source.id}",
                daemon=True,
            )
            for source in starting
        ]
        for thread in threads:
            thread.start()
        return threads

    def _work(self, store: DocumentStore, source: ServedSource) -> None:
        """やり直しの要求が無くなるまで、配信元を検査し直す。"""
        while True:
            try:
                self.refresh(store, source)
            except Exception:
                logger.exception("配信元の検査に失敗した（%s）", source.id)
            with self._lock:
                if source.id in self._requested:
                    self._requested.discard(source.id)
                    continue
                self._running.discard(source.id)
                return

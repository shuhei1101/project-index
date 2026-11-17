"""配信元ごとの検査の結果。"""

from __future__ import annotations

from project_index import poc_timing

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from project_index.features.documents.store import DocumentStore, check_sync
from project_index.features.documents.types import SyncReport
from project_index.features.read.nav import nav_warnings
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
        self, on_checked: Callable[[ServedSource, SourceCheck], None] | None = None
    ) -> None:
        # 結果を置き換えた検査ごとに呼ぶ（起動では警告のログを書く関数）
        self.on_checked = on_checked
        self._lock = threading.Lock()
        self._results: dict[str, tuple[int, SourceCheck]] = {}
        # 配信元ごとの、始めた検査の数
        self._started: dict[str, int] = {}
        self._running: set[str] = set()
        # 裏で検査中に要求された配信元の ID → 最後に要求された配信元
        self._requested: dict[str, ServedSource] = {}

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
        with poc_timing.span("source_check", source=source.id):
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
        """裏で検査していない配信元を裏のスレッドで検査し直し、待たずに戻る。"""
        starting: list[ServedSource] = []
        # PoC: 裏の検査を止める
        if poc_timing.flag("POC_NO_CHECKS"):
            poc_timing.emit("checks_skipped")
            return []
        with self._lock:
            for source in sources:
                # 検査中の配信元は、終えた後にもう 1 回流すよう要求だけを立てる
                if source.id in self._running:
                    self._requested[source.id] = source
                else:
                    self._running.add(source.id)
                    starting.append(source)
        if poc_timing.flag("POC_FIX"):
            # PoC の修正: 1 つのスレッドで配信元を順に検査し、応答中の要求があれば次の配信元の前で待つ
            def sequential() -> None:
                for source in starting:
                    poc_timing.wait_idle("check_wait_idle", source=source.id)
                    self._work(store, source)

            threads = [
                threading.Thread(target=sequential, name="project-index-source-checks", daemon=True)
            ]
        else:
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
                # 検査中に要求があれば、要求された最新の配信元でもう 1 回検査する
                if source.id in self._requested:
                    source = self._requested.pop(source.id)
                    continue
                self._running.discard(source.id)
                return

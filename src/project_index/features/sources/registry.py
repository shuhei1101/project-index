"""配信元の一覧と読み直し。"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import threading
from typing import TYPE_CHECKING

from project_index.features.history.query import resolve_ref
from project_index.features.sources.schema_ref import SchemaRefLookup, terminal_lookup
from project_index.features.sources.service import load_source
from project_index.features.sources.types import ServedSource, SourceStatus
from project_index.shared.errors import (
    ProjectIndexError,
    SourceNotServedError,
    UnknownSourceError,
    Violation,
)
from project_index.shared.paths import match_glob, normalize_path

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from project_index.features.settings.types import SourceEntry, TerminalConfig

logger = logging.getLogger(__name__)

__all__ = ["SourceRegistry", "load_source"]


type _Waiter = tuple[asyncio.AbstractEventLoop, asyncio.Future[None], frozenset[int] | None]


class SourceRegistry:
    """配信中の配信元と状態を持ち、読み直しで一覧ごと差し替える。"""

    def __init__(
        self,
        on_rebuilt: Callable[[ServedSource], None] | None = None,
        *,
        loading: bool = False,
        on_waiting: Callable[[], None] | None = None,
    ) -> None:
        self._snapshot: tuple[dict[str, ServedSource], list[SourceStatus]] = ({}, [])
        self._reload_lock = threading.Lock()
        self._entries: dict[str, tuple[SourceEntry, int]] = {}
        # 最後に読み直した端末の設定から作った、参照先の配信元の引き当て
        self._lookup: SchemaRefLookup | None = None
        self._on_rebuilt = on_rebuilt
        self._ready = threading.Event()
        if not loading:
            self._ready.set()
        # 待ち手の行が None のときは、全ての行の読み込み（_ready）を待つ
        self._waiters: list[_Waiter] = []
        self._waiters_lock = threading.Lock()
        self._rows: list[SourceEntry] = []
        self._rows_done: list[threading.Event] = []
        self._requested: list[int] = []
        self._on_waiting = on_waiting

    @property
    def loading(self) -> bool:
        """全ての行の初回の読み込みが終わっていなければ `True`。"""
        return not self._ready.is_set()

    async def wait_loaded(self) -> None:
        """全ての行の初回の読み込みが終わるまで、スレッドを持たずに待つ。"""
        await self.wait_for(every=True)

    async def wait_for(
        self,
        *,
        ids: Sequence[str] | None = None,
        cwd: str | None = None,
        every: bool = False,
    ) -> None:
        """要求が指す配信元の行の読み込みだけを、スレッドを持たずに待つ。"""
        if self._ready.is_set() or (ids is None and cwd is None and not every):
            return
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        with self._waiters_lock:
            if self._ready.is_set():
                return
            pending: frozenset[int] | None = None
            # 行が決まる前（load の前）は、全ての行の読み込みを待つ
            if self._rows_done:
                rows = range(len(self._rows)) if every else self._target_rows(ids, cwd)
                pending = frozenset(index for index in rows if not self._rows_done[index].is_set())
                if not pending:
                    return
                self._request(pending)
            waiter: _Waiter = (loop, future, pending)
            self._waiters.append(waiter)
        if self._on_waiting is not None:
            self._on_waiting()
        try:
            await future
        except asyncio.CancelledError:
            with self._waiters_lock, contextlib.suppress(ValueError):
                self._waiters.remove(waiter)
            raise

    def _target_rows(self, ids: Sequence[str] | None, cwd: str | None) -> list[int]:
        """ID か作業場所が指す行の位置を返す（`_waiters_lock` の中で呼ぶ）。"""
        if ids is not None:
            found: set[int] = set()
            for source_id in ids:
                found.update(self._id_rows(source_id))
            return sorted(found)
        if cwd is None:
            return []
        path = normalize_path(cwd)
        matched = [
            index
            for index, entry in enumerate(self._rows)
            if match_glob(path, [*(entry.scope.write or []), *entry.scope.read])
        ]
        # ワークツリーの照合は設定を読み込むまでできないため、当たる行が無ければ全ての行
        return matched or list(range(len(self._rows)))

    def _id_rows(self, source_id: str) -> list[int]:
        """ID を指す行の位置。その ID の行が無ければ、ID を持たない行の全て。"""
        rows = [index for index, entry in enumerate(self._rows) if entry.id == source_id]
        if rows:
            return rows
        return [index for index, entry in enumerate(self._rows) if entry.id is None]

    def _request(self, rows: frozenset[int]) -> None:
        """待っている行を、先に読み込む行の並びの後ろへ足す（`_waiters_lock` の中で呼ぶ）。"""
        for index in sorted(rows):
            if index not in self._requested:
                self._requested.append(index)

    def _finish_waiters(self, *, every: bool) -> None:
        """待っている行が全て済んだ待ち手（`every` なら全て）の Future を済ませる。"""
        with self._waiters_lock:
            finished = [
                waiter
                for waiter in self._waiters
                if every
                or (
                    waiter[2] is not None
                    and all(self._rows_done[index].is_set() for index in waiter[2])
                )
            ]
            self._waiters = [waiter for waiter in self._waiters if waiter not in finished]
        for loop, future, _ in finished:
            if loop.is_closed():
                continue
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(_finish, future)

    def _release_waiters(self) -> None:
        """全ての行と読み込みの済みを立て、待っている待ち手を全て済ませる。"""
        for done in self._rows_done:
            done.set()
        self._ready.set()
        self._finish_waiters(every=True)

    def load(self, terminal: TerminalConfig) -> None:
        """起動のときに、端末の設定の行を 1 つずつ読み込み、読み込み終えた行から配信する。"""
        with self._waiters_lock:
            self._rows = list(terminal.sources)
            self._rows_done = [threading.Event() for _ in self._rows]
        try:
            # ほかの配信元のスキーマの参照先は端末の設定から引き、行の読み込みを待たない
            lookup = terminal_lookup(terminal)
            with self._reload_lock:
                self._lookup = lookup
            while (index := self._next_row()) is not None:
                entry = self._rows[index]
                served, status = self._load_row(entry, index, lookup)
                self._publish(entry, index, served, status)
                self._rows_done[index].set()
                self._finish_waiters(every=False)
            sources, statuses = self._snapshot
            logger.info(
                "配信元を読み直した（配信中: %s・外した数: %s）",
                list(sources),
                sum(1 for status in statuses if status.status == "not_served"),
            )
        finally:
            self._release_waiters()

    def _next_row(self) -> int | None:
        """次に読み込む行。待っている要求が指す行を先にし、無ければ位置の順。"""
        with self._waiters_lock:
            candidates: list[int] = [*self._requested, *range(len(self._rows))]
            for index in candidates:
                if not self._rows_done[index].is_set():
                    return index
        return None

    @staticmethod
    def _load_row(
        entry: SourceEntry, index: int, lookup: SchemaRefLookup
    ) -> tuple[ServedSource | None, SourceStatus]:
        """行を読む。例外のときは、その行を配信しない状態にする。"""
        try:
            return load_source(entry, index=index, lookup=lookup)
        except Exception as error:
            logger.exception("配信元の行の読み込みに失敗した（sources[%s]）", index)
            return None, SourceStatus(
                id=entry.id or f"sources[{index}]",
                index=index,
                status="not_served",
                config=tuple(entry.config),
                errors=[
                    Violation(
                        path=f"sources[{index}]",
                        rule=f"読み込みに失敗しました（{type(error).__name__}: {error}）",
                        fix="エラーログを確かめ、reload で読み直してください",
                    )
                ],
            )

    def _publish(
        self,
        entry: SourceEntry,
        index: int,
        served: ServedSource | None,
        status: SourceStatus,
    ) -> None:
        """読み込んだ行を今の組に加え、組を入れ替える。"""
        with self._reload_lock:
            current, current_statuses = self._snapshot
            sources = dict(current)
            entries = dict(self._entries)
            statuses = [item for item in current_statuses if item.index != index]
            if served is not None and served.id in entries:
                other_entry, other = entries[served.id]
                if other < index:
                    # 先の位置の行が配信中なので、この行を外す
                    status = _duplicate_status(served.id, index, entry)
                    served = None
                else:
                    # 後の位置の行が先に読み込まれていたので、その行を外す
                    statuses = [
                        _duplicate_status(served.id, other, other_entry)
                        if item.index == other
                        else item
                        for item in statuses
                    ]
                    del sources[served.id]
                    del entries[served.id]
            if served is not None:
                sources[served.id] = served
                entries[served.id] = (entry, index)
            statuses.append(status)
            statuses.sort(key=lambda item: item.index)
            self._entries = entries
            self._snapshot = (sources, statuses)

    def reload(self, terminal: TerminalConfig) -> list[SourceStatus]:
        """端末の設定の全行を読み直し、一覧を差し替える。"""
        try:
            return self._reload(terminal)
        finally:
            self._release_waiters()

    def _reload(self, terminal: TerminalConfig) -> list[SourceStatus]:
        """全行を読み、一覧を差し替える（例外のときは差し替えない）。"""
        with self._reload_lock:
            sources: dict[str, ServedSource] = {}
            statuses: list[SourceStatus] = []
            entries: dict[str, tuple[SourceEntry, int]] = {}
            # ほかの配信元のスキーマの参照先は、読み直す端末の設定から引く
            lookup = terminal_lookup(terminal)
            for index, entry in enumerate(terminal.sources):
                served, status = load_source(entry, index=index, lookup=lookup)
                # 配信する配信元の ID が先の行と重なるときは、後の行を外す
                if served is not None and served.id in sources:
                    status = _duplicate_status(served.id, index, entry)
                    served = None
                if served is not None:
                    sources[served.id] = served
                    entries[served.id] = (entry, index)
                statuses.append(status)
            self._entries = entries
            self._lookup = lookup
            self._snapshot = (sources, statuses)
            with self._waiters_lock:
                self._rows = list(terminal.sources)
                self._rows_done = [threading.Event() for _ in self._rows]
            logger.info(
                "配信元を読み直した（配信中: %s・外した数: %s）",
                list(sources),
                sum(1 for status in statuses if status.status == "not_served"),
            )
            return statuses

    def reload_changed(self, terminal: TerminalConfig) -> list[SourceStatus]:
        """前に読んだ行と同じ行は今の配信元を使い回し、変わった行だけを読み込んで一覧を差し替える。"""
        try:
            return self._reload_changed(terminal)
        finally:
            self._release_waiters()

    def _previous_rows(self) -> list[tuple[SourceEntry, ServedSource | None, SourceStatus]]:
        """前に読んだ行ごとに、行と配信中の配信元（無ければ None）と状態を並べる。"""
        sources, statuses = self._snapshot
        by_index = {status.index: status for status in statuses}
        rows: list[tuple[SourceEntry, ServedSource | None, SourceStatus]] = []
        for index, entry in enumerate(self._rows):
            status = by_index.get(index)
            if status is None:
                continue
            owner = self._entries.get(status.id)
            served = sources.get(status.id) if owner is not None and owner[1] == index else None
            rows.append((entry, served, status))
        return rows

    def _reload_changed(self, terminal: TerminalConfig) -> list[SourceStatus]:
        """変わった行だけを読み、一覧を差し替える（例外のときは差し替えない）。"""
        with self._reload_lock:
            previous = self._previous_rows()
            used: set[int] = set()
            sources: dict[str, ServedSource] = {}
            statuses: list[SourceStatus] = []
            entries: dict[str, tuple[SourceEntry, int]] = {}
            loaded: list[int] = []
            lookup = terminal_lookup(terminal)
            for index, entry in enumerate(terminal.sources):
                reused = self._reuse(previous, used, entry)
                # 前に読んだ同じ値の行があり、配信中か無効: 配信元と状態を使い回して位置だけ替える
                if reused is not None:
                    served, old = reused
                    status = dataclasses.replace(old, index=index)
                else:
                    # 変わった行か、配信していなかった行: 読み込む
                    served, status = load_source(entry, index=index, lookup=lookup)
                    loaded.append(index)
                # 配信する配信元の ID が先の行と重なるときは、後の行を外す
                if served is not None and served.id in sources:
                    status = _duplicate_status(served.id, index, entry)
                    served = None
                if served is not None:
                    sources[served.id] = served
                    entries[served.id] = (entry, index)
                statuses.append(status)
            self._entries = entries
            self._lookup = lookup
            self._snapshot = (sources, statuses)
            with self._waiters_lock:
                self._rows = list(terminal.sources)
                self._rows_done = [threading.Event() for _ in self._rows]
            logger.info("変わった行の配信元を読み直した（読んだ行: %s・配信中: %s）", loaded, list(sources))
            return statuses

    @staticmethod
    def _reuse(
        previous: list[tuple[SourceEntry, ServedSource | None, SourceStatus]],
        used: set[int],
        entry: SourceEntry,
    ) -> tuple[ServedSource | None, SourceStatus] | None:
        """前に読んだ行のうち、値が同じで使っていない行の配信元と状態を返す（`not_served` は使い回さない）。"""
        for position, (old_entry, served, status) in enumerate(previous):
            if position in used or old_entry != entry:
                continue
            if status.status == "not_served":
                return None
            used.add(position)
            return served, status
        return None

    def get(self, source_id: str) -> ServedSource:
        """配信中の配信元を ID で引く。読み込んでいない行の ID は、その行の読み込みを待つ。"""
        self._wait_row(source_id)
        sources, statuses = self._snapshot
        if source_id in sources:
            return self._refresh(sources[source_id])
        for status in statuses:
            if status.id == source_id and status.status in ("not_served", "disabled"):
                disabled = status.status == "disabled"
                reason = (
                    "無効です"
                    if disabled
                    else "; ".join(f"{v.path}: {v.rule}" for v in status.errors)
                )
                raise SourceNotServedError(
                    message=f"{source_id} は配信していません（{reason}）",
                    violations=status.errors,
                    disabled=disabled,
                )
        raise UnknownSourceError(message=f"配信元 {source_id} はありません", source_id=source_id)

    def _wait_row(self, source_id: str) -> None:
        """`load` の間に、まだ読み込んでいない行の ID を引いた場合、その行の読み込みを待つ。"""
        if self._ready.is_set() or source_id in self._snapshot[0]:
            return
        with self._waiters_lock:
            if not self._rows_done:
                return
            pending = frozenset(
                index for index in self._id_rows(source_id) if not self._rows_done[index].is_set()
            )
            self._request(pending)
        for index in sorted(pending):
            self._rows_done[index].wait()

    def _current_commit(self, source: ServedSource) -> str | None:
        """配信元の `default_ref` の今の commit。解けなければ `None`。"""
        if source.repo_root is None:
            return None
        default_ref = source.config.default_ref
        try:
            return resolve_ref(source.repo_root, default_ref, date_base=default_ref).commit
        except ProjectIndexError:
            return None

    def _refresh(self, source: ServedSource) -> ServedSource:
        """`default_ref` が進んでいれば、その配信元だけを組み立て直して差し替える。"""
        if source.config_commit is None:
            return source
        current = self._current_commit(source)
        if current is None or current == source.config_commit:
            return source
        with self._reload_lock:
            sources, statuses = self._snapshot
            latest = sources.get(source.id, source)
            if latest.config_commit == current or source.id not in self._entries:
                return latest
            entry, index = self._entries[source.id]
            served, status = load_source(entry, index=index, lookup=self._lookup)
            next_sources = dict(sources)
            if served is None:
                next_sources.pop(source.id, None)
            else:
                next_sources[source.id] = served
            next_statuses = [status if item.index == index else item for item in statuses]
            self._snapshot = (next_sources, next_statuses)
            logger.info(
                "default_ref が進んだので配信元を組み立て直した（%s・%s → %s）",
                source.id,
                source.config_commit,
                current,
            )
            if served is not None and self._on_rebuilt is not None:
                self._on_rebuilt(served)
        if served is None:
            return self.get(source.id)
        return served

    def served(self) -> list[ServedSource]:
        """配信中の配信元を `sources[]` の順に返す。"""
        sources, statuses = self._snapshot
        return [
            sources[status.id]
            for status in statuses
            if status.status == "serving" and status.id in sources
        ]

    def statuses(self) -> list[SourceStatus]:
        """`sources[]` の順の状態を返す。"""
        return self._snapshot[1]


def _duplicate_status(source_id: str, index: int, entry: SourceEntry) -> SourceStatus:
    """配信する配信元の ID が他の行と重なる行の状態。"""
    return SourceStatus(
        id=source_id,
        index=index,
        status="not_served",
        config=tuple(entry.config),
        errors=[
            Violation(
                path=f"sources[{index}].id",
                rule=f"{source_id} は既に使用されています",
                fix="sources[].id を別の値にしてください",
            )
        ],
    )


def _finish(future: asyncio.Future[None]) -> None:
    """済んでいない Future を済ませる。"""
    if not future.done():
        future.set_result(None)

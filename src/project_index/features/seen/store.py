"""会話ごとの記録の SQLite への読み書き。"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast

from project_index.features.seen.types import (
    Activity,
    ActivityKind,
    LastRead,
    ReturnKind,
    SessionKey,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from project_index.features.documents.types import Document

SEEN_SCHEMA = """\
CREATE TABLE IF NOT EXISTS returned (
  session_id TEXT NOT NULL, agent_id TEXT NOT NULL, source_id TEXT NOT NULL,
  kind TEXT NOT NULL, doc_id TEXT NOT NULL, version TEXT NOT NULL,
  doc_kind TEXT NOT NULL, content TEXT, at TEXT NOT NULL,
  PRIMARY KEY (session_id, agent_id, source_id, kind, doc_id));
CREATE TABLE IF NOT EXISTS activity (
  session_id TEXT NOT NULL, agent_id TEXT NOT NULL, source_id TEXT NOT NULL,
  doc_id TEXT NOT NULL, kind TEXT NOT NULL, at TEXT NOT NULL,
  PRIMARY KEY (session_id, agent_id, source_id, doc_id, kind));
"""

TABLES = ("returned", "activity")


def _now() -> str:
    """今の UTC を ISO 8601 の文字列にする。"""
    return datetime.now(UTC).isoformat()


class SeenStore:
    """会話キーごとの返却済み・前回読んだ内容・閲覧と編集を SQLite に読み書きする。"""

    def __init__(self, path: Path, retention_days: int) -> None:
        self.path = path
        self.retention_days = retention_days
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SEEN_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        """接続を閉じる。"""
        with self._lock:
            self._conn.close()

    def __del__(self) -> None:
        with contextlib.suppress(AttributeError, sqlite3.Error):
            self._conn.close()

    def returned(
        self,
        key: SessionKey | None,
        source_id: str,
        kind: ReturnKind,
        versions: Mapping[str, str],
    ) -> set[str]:
        """同じバージョンをこの会話で返却済みの文書の ID を返す。"""
        if key is None or not versions:
            return set()
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc_id, version FROM returned "
                "WHERE session_id = ? AND agent_id = ? AND source_id = ? AND kind = ?",
                (key.session_id, key.agent_id, source_id, kind),
            ).fetchall()
        return {doc_id for doc_id, version in rows if versions.get(doc_id) == version}

    def mark_returned(
        self,
        key: SessionKey | None,
        source_id: str,
        kind: ReturnKind,
        documents: Sequence[Document],
    ) -> None:
        """返した文書のバージョンを記録し、本文なら内容と閲覧も記録する。"""
        if key is None or not documents:
            return
        at = _now()
        with self._lock, self._conn:
            for document in documents:
                content = document.body if kind == "body" else None
                self._conn.execute(
                    "INSERT OR REPLACE INTO returned VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key.session_id,
                        key.agent_id,
                        source_id,
                        kind,
                        document.id,
                        document.version,
                        document.kind,
                        content,
                        at,
                    ),
                )
                if kind == "body":
                    self._conn.execute(
                        "INSERT OR REPLACE INTO activity VALUES (?, ?, ?, ?, 'viewed', ?)",
                        (key.session_id, key.agent_id, source_id, document.id, at),
                    )

    def last_read(self, key: SessionKey | None, source_id: str) -> dict[str, LastRead]:
        """この会話で最後に本文を返したときの内容を返す。"""
        if key is None:
            return {}
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc_id, version, doc_kind, content, at FROM returned "
                "WHERE session_id = ? AND agent_id = ? AND source_id = ? AND kind = 'body'",
                (key.session_id, key.agent_id, source_id),
            ).fetchall()
        return {
            doc_id: LastRead(
                doc_id=doc_id,
                version=version,
                doc_kind=doc_kind,
                content=content or "",
                read_at=datetime.fromisoformat(at),
            )
            for doc_id, version, doc_kind, content, at in rows
        }

    def record_activity(
        self,
        key: SessionKey | None,
        source_id: str,
        doc_ids: Sequence[str],
        kind: ActivityKind,
    ) -> None:
        """書いた文書を編集として記録する。"""
        if key is None or not doc_ids:
            return
        at = _now()
        with self._lock, self._conn:
            for doc_id in doc_ids:
                self._conn.execute(
                    "INSERT OR REPLACE INTO activity VALUES (?, ?, ?, ?, ?, ?)",
                    (key.session_id, key.agent_id, source_id, doc_id, kind, at),
                )

    def activity(self, key: SessionKey | None, source_id: str) -> list[Activity]:
        """この会話で閲覧・編集した文書を返す。"""
        if key is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT doc_id, kind, at FROM activity "
                "WHERE session_id = ? AND agent_id = ? AND source_id = ? "
                "ORDER BY at DESC, rowid DESC",
                (key.session_id, key.agent_id, source_id),
            ).fetchall()
        return [
            Activity(
                doc_id=doc_id,
                kind=cast("Literal['viewed', 'edited']", kind),
                at=datetime.fromisoformat(at),
            )
            for doc_id, kind, at in rows
        ]

    def forget(self, key: SessionKey) -> int:
        """1 つの会話キーの記録を全て消す。"""
        params: tuple[str, ...]
        if key.agent_id:
            condition, params = "session_id = ? AND agent_id = ?", (key.session_id, key.agent_id)
        else:
            condition, params = "session_id = ?", (key.session_id,)
        removed = 0
        with self._lock, self._conn:
            for table in TABLES:
                removed += self._conn.execute(
                    f"DELETE FROM {table} WHERE {condition}",  # noqa: S608
                    params,
                ).rowcount
        return removed

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """保持日数を過ぎた会話の記録を消す。"""
        cutoff = (now or datetime.now(UTC)) - timedelta(days=self.retention_days)
        removed = 0
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT session_id, MAX(at) FROM ("
                "SELECT session_id, at FROM returned UNION ALL SELECT session_id, at FROM activity)"
                " GROUP BY session_id"
            ).fetchall()
            expired = [
                session_id for session_id, last in rows if datetime.fromisoformat(last) < cutoff
            ]
            for session_id in expired:
                for table in TABLES:
                    removed += self._conn.execute(
                        f"DELETE FROM {table} WHERE session_id = ?",  # noqa: S608
                        (session_id,),
                    ).rowcount
        return removed

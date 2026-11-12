from __future__ import annotations

import contextlib
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from project_index.features.seen.store import SeenStore
from project_index.features.seen.types import SessionKey

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.documents.types import Document


@pytest.fixture
def seen_store(tmp_path: Path) -> SeenStore:
    """保持日数 7 日の会話の記録を返す。"""
    return SeenStore(tmp_path / "seen.sqlite3", retention_days=7)


def test_seen_store_returned(seen_store: SeenStore, make_document: Callable[..., Document]) -> None:
    """同じバージョンだけ返し済み（正常系）。"""
    # 準備
    key = SessionKey("s1")
    documents = [
        make_document(id="doc-1", version="v1"),
        make_document(id="doc-2", version="v1"),
    ]
    seen_store.mark_returned(key, "sample", "body", documents)
    # 実行
    result = seen_store.returned(key, "sample", "body", {"doc-1": "v1", "doc-2": "v2"})
    # 検証
    assert result == {"doc-1"}


def test_seen_store_returned_when_other_key(
    seen_store: SeenStore, make_document: Callable[..., Document]
) -> None:
    """会話キーとサブエージェントを分ける（正常系）。"""
    # 準備
    seen_store.mark_returned(
        SessionKey("s1"), "sample", "body", [make_document(id="doc-1", version="v1")]
    )
    versions = {"doc-1": "v1"}
    # 実行
    sub_agent = seen_store.returned(SessionKey("s1", "a1"), "sample", "body", versions)
    other_session = seen_store.returned(SessionKey("s2"), "sample", "body", versions)
    without_key = seen_store.returned(None, "sample", "body", versions)
    # 検証
    assert sub_agent == set()
    assert other_session == set()
    assert without_key == set()


def test_seen_store_mark_returned(
    seen_store: SeenStore, make_document: Callable[..., Document]
) -> None:
    """本文は内容と閲覧も残す（正常系）。"""
    # 準備
    key = SessionKey("s1")
    seen_store.mark_returned(key, "sample", "body", [make_document(id="doc-1", body="id: doc-1\n")])
    seen_store.mark_returned(key, "sample", "related", [make_document(id="doc-2")])
    # 実行
    last_read = seen_store.last_read(key, "sample")
    activity = seen_store.activity(key, "sample")
    # 検証
    assert list(last_read) == ["doc-1"]
    assert last_read["doc-1"].content == "id: doc-1\n"
    assert [(item.doc_id, item.kind) for item in activity] == [("doc-1", "viewed")]


def test_seen_store_activity(seen_store: SeenStore, make_document: Callable[..., Document]) -> None:
    """閲覧と編集を新しい順に返す（正常系）。"""
    # 準備
    key = SessionKey("s1")
    seen_store.mark_returned(key, "sample", "body", [make_document(id="doc-1")])
    seen_store.record_activity(key, "sample", ["doc-2"], "edited")
    # 実行
    result = seen_store.activity(key, "sample")
    # 検証
    assert [(item.doc_id, item.kind) for item in result] == [
        ("doc-2", "edited"),
        ("doc-1", "viewed"),
    ]


def test_seen_store_forget(seen_store: SeenStore, make_document: Callable[..., Document]) -> None:
    """メインの会話を消すとサブエージェントも消える（正常系）。"""
    # 準備
    keys = [SessionKey("s1"), SessionKey("s1", "a1"), SessionKey("s2")]
    for key in keys:
        seen_store.mark_returned(key, "sample", "body", [make_document(id="doc-1")])
    # 実行
    seen_store.forget(SessionKey("s1"))
    # 検証
    versions = {"doc-1": "9d0e11"}
    assert seen_store.returned(keys[0], "sample", "body", versions) == set()
    assert seen_store.returned(keys[1], "sample", "body", versions) == set()
    assert seen_store.returned(keys[2], "sample", "body", versions) == {"doc-1"}


def _insert_session(path: Path, session_id: str, at: datetime) -> None:
    """会話 1 つの記録を、決めた日時で 2 つの表に直接入れる。"""
    with contextlib.closing(sqlite3.connect(path)) as conn, conn:
        conn.execute(
            "INSERT INTO returned VALUES (?, '', 'sample', 'body', 'doc-1', 'v1', 'rules', 'x', ?)",
            (session_id, at.isoformat()),
        )
        conn.execute(
            "INSERT INTO activity VALUES (?, '', 'sample', 'doc-1', 'viewed', ?)",
            (session_id, at.isoformat()),
        )


def test_seen_store_purge_expired(seen_store: SeenStore) -> None:
    """保持日数を過ぎた会話だけ消す（正常系）。"""
    # 準備
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    _insert_session(seen_store.path, "old", now - timedelta(days=8))
    _insert_session(seen_store.path, "new", now - timedelta(days=1))
    # 実行
    removed = seen_store.purge_expired(now=now)
    # 検証
    versions = {"doc-1": "v1"}
    assert removed > 1
    assert seen_store.returned(SessionKey("old"), "sample", "body", versions) == set()
    assert seen_store.returned(SessionKey("new"), "sample", "body", versions) == {"doc-1"}

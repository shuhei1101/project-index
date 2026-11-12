from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.seen.store import SeenStore
from project_index.features.seen.types import SessionKey
from project_index.features.session_start.service import start_session
from project_index.features.session_start.types import SessionStartRequest

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from project_index.features.documents.types import Document


def _seen(tmp_path: Path) -> SeenStore:
    """一時ディレクトリの会話の記録を作る。"""
    return SeenStore(tmp_path / "seen.sqlite3", retention_days=7)


def test_start_session_when_cleared(tmp_path: Path, make_document: Callable[..., Document]) -> None:
    """/clear の後は返し済みの記録を削除する（正常系）。"""
    # 準備
    seen = _seen(tmp_path)
    key = SessionKey("s1", "")
    seen.mark_returned(key, "sample", "body", [make_document()])
    request = SessionStartRequest(session_id="s1", reason="clear")
    # 実行
    result = start_session(request, seen=seen)
    # 検証
    assert result.forgotten is True
    assert seen.last_read(key, "sample") == {}


def test_start_session_when_compacted(
    tmp_path: Path, make_document: Callable[..., Document]
) -> None:
    """圧縮の後も削除する（正常系）。"""
    # 準備
    seen = _seen(tmp_path)
    agent_key = SessionKey("s1", "a1")
    main_key = SessionKey("s1", "")
    seen.mark_returned(agent_key, "sample", "body", [make_document()])
    seen.mark_returned(main_key, "sample", "body", [make_document()])
    request = SessionStartRequest(session_id="s1", agent_id="a1", reason="compact")
    # 実行
    result = start_session(request, seen=seen)
    # 検証
    assert result.forgotten is True
    assert seen.last_read(agent_key, "sample") == {}
    assert list(seen.last_read(main_key, "sample")) == ["doc-1"]


def test_start_session_when_resumed(tmp_path: Path, make_document: Callable[..., Document]) -> None:
    """再開では記録を削除しない（正常系）。"""
    # 準備
    seen = _seen(tmp_path)
    key = SessionKey("s1", "")
    seen.mark_returned(key, "sample", "body", [make_document()])
    request = SessionStartRequest(session_id="s1", reason="resume")
    # 実行
    result = start_session(request, seen=seen)
    # 検証
    assert result.forgotten is False
    assert list(seen.last_read(key, "sample")) == ["doc-1"]

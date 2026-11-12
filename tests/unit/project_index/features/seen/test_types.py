from __future__ import annotations

from project_index.features.seen.types import SessionKey


def test_session_key_of() -> None:
    """会話キーを作る（正常系）。"""
    # 実行
    with_session = SessionKey.of("s1", None)
    without_session = SessionKey.of(None, "a1")
    # 検証
    assert with_session == SessionKey("s1", "")
    assert without_session is None

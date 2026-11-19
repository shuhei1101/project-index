from __future__ import annotations

from project_index.features.post_write.notified import NotifiedStore
from project_index.features.seen.types import SessionKey


def test_take_new() -> None:
    """2 回目は同じパスを返さない（正常系）。"""
    # 準備
    store = NotifiedStore()
    key = SessionKey("s1", "")
    # 実行
    first = store.take_new(key, ["/a"])
    second = store.take_new(key, ["/a"])
    # 検証
    assert first == ["/a"]
    assert second == []


def test_take_new_when_other_key() -> None:
    """会話キーごとに分ける（正常系）。"""
    # 準備
    store = NotifiedStore()
    store.take_new(SessionKey("s1", ""), ["/a"])
    # 実行
    agent = store.take_new(SessionKey("s1", "a1"), ["/a"])
    other = store.take_new(SessionKey("s2", ""), ["/a"])
    # 検証
    assert agent == ["/a"]
    assert other == ["/a"]


def test_forget() -> None:
    """消した後は再び返す（正常系）。"""
    # 準備
    store = NotifiedStore()
    key = SessionKey("s1", "")
    store.take_new(key, ["/a"])
    # 実行
    forgotten = store.forget(key)
    again = store.take_new(key, ["/a"])
    # 検証
    assert forgotten == 1
    assert again == ["/a"]

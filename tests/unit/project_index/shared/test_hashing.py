from __future__ import annotations

from project_index.shared.hashing import content_hash, value_hash


def test_content_hash() -> None:
    """文字列とバイト列で同じ（正常系）。"""
    # 実行
    from_text = content_hash("a")
    from_bytes = content_hash(b"a")
    # 検証
    assert from_text == "ca9781"
    assert from_bytes == "ca9781"


def test_value_hash() -> None:
    """キーの順によらない（正常系）。"""
    # 実行
    first = value_hash({"a": 1, "b": 2})
    second = value_hash({"b": 2, "a": 1})
    # 検証
    assert first == second

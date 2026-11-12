from __future__ import annotations

from project_index.features.changes.compare import changed_keys, count_occurrences, diff_lines
from project_index.features.changes.types import ContainsQuery


def test_changed_keys() -> None:
    """入れ子と要素の突き合わせ（正常系）。"""
    # 準備
    before = {"name": "a", "items": [{"id": "x", "v": 1}], "updated": "d1"}
    after = {"name": "b", "items": [{"id": "x", "v": 2}], "updated": "d2"}
    # 実行
    result = changed_keys(before, after, ignore=["updated"])
    # 検証
    assert result == {"name": ("a", "b"), "items[x].v": (1, 2)}


def test_diff_lines() -> None:
    """変えた行（正常系）。"""
    # 実行
    result = diff_lines("name: 文書 1\nx: 1\n", "name: 新しい名前\nx: 1\n")
    # 検証
    assert result == "- name: 文書 1\n+ name: 新しい名前"


def test_count_occurrences() -> None:
    """大文字小文字と全角半角を区別しない（正常系）。"""
    # 実行
    result = count_occurrences("ＡＢＣ abc Abc", ContainsQuery(value="abc"))
    # 検証
    assert result == 3


def test_count_occurrences_when_case_sensitive() -> None:
    """区別する（正常系）。"""
    # 実行
    result = count_occurrences("ＡＢＣ abc Abc", ContainsQuery(value="abc", case_sensitive=True))
    # 検証
    assert result == 1


def test_count_occurrences_when_regex() -> None:
    """正規表現の当たった数（正常系）。"""
    # 実行
    result = count_occurrences(
        "廃止予定\n廃止の予定\n廃止予定", ContainsQuery(value="廃止.定", regex=True)
    )
    # 検証
    assert result == 2

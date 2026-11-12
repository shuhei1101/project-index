from __future__ import annotations

import pytest
from project_index.features.search.cursor import decode_cursor, encode_cursor
from project_index.shared.errors import InvalidArgumentError


def test_decode_cursor() -> None:
    """往復（正常系）。"""
    # 準備
    cursor = encode_cursor(40, "f1")
    # 実行
    result = decode_cursor(cursor, "f1")
    # 検証
    assert result == 40


def test_decode_cursor_when_other_request() -> None:
    """引数が違う（異常系）。"""
    # 準備
    cursor = encode_cursor(40, "f1")
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        decode_cursor(cursor, "f2")
    assert exc_info.value.violations[0].path == "cursor"

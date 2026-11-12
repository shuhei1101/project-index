from __future__ import annotations

import pytest
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from project_index.shared.narrowing import is_dict, is_list


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param({"a": 1}, True, id="dict"),
        pytest.param(CommentedMap(), True, id="commented_map"),
        pytest.param([1], False, id="list"),
        pytest.param("a", False, id="str"),
        pytest.param(None, False, id="none"),
    ],
)
def test_is_dict(value: object, expected: bool) -> None:
    """辞書と辞書でない値（正常系）。"""
    # 実行
    judged = is_dict(value)
    # 検証
    assert judged is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param([1], True, id="list"),
        pytest.param(CommentedSeq(), True, id="commented_seq"),
        pytest.param((1,), False, id="tuple"),
        pytest.param({"a": 1}, False, id="dict"),
        pytest.param(None, False, id="none"),
    ],
)
def test_is_list(value: object, expected: bool) -> None:
    """配列と配列でない値（正常系）。"""
    # 実行
    judged = is_list(value)
    # 検証
    assert judged is expected

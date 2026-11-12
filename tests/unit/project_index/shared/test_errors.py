from __future__ import annotations

from project_index.shared.errors import LastReadNotFoundError, SourceNotServedError, Violation


def test_project_index_error_details() -> None:
    """追加のプロパティを辞書にする（正常系）。"""
    # 準備
    error = SourceNotServedError(
        violations=[Violation(path="documents[0].paths", rule="必須のキーが無い")],
        disabled=False,
    )
    # 実行
    result = error.details()
    # 検証
    assert result == {
        "violations": [
            {
                "path": "documents[0].paths",
                "rule": "必須のキーが無い",
                "fix": "",
                "index": None,
                "doc": None,
            }
        ],
        "disabled": False,
    }


def test_project_index_error_details_when_no_extra() -> None:
    """追加のプロパティが無い（正常系）。"""
    # 準備
    error = LastReadNotFoundError(message="…")
    # 実行
    result = error.details()
    # 検証
    assert result == {}

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from project_index.features.validation import markdown as markdown_module
from project_index.features.validation.markdown import (
    UncheckedKey,
    changed_markdown,
    check_markdown_values,
    markdown_values,
)
from project_index.integrations.mdmark import MdmarkFinding, MdmarkUnavailableError
from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from pathlib import Path

MARKDOWN = {"type": "string", "contentMediaType": "text/markdown"}

BODY_LEAD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"body": MARKDOWN, "lead": MARKDOWN},
}


def test_markdown_values() -> None:
    """入れ子と配列と参照をたどる（正常系）。"""
    # 準備
    schema = {
        "type": "object",
        "$defs": {"md": {"type": "string", "contentMediaType": "text/markdown"}},
        "properties": {
            "body": {"$ref": "#/$defs/md"},
            "items": {
                "type": "array",
                "items": {"type": "object", "properties": {"note": {"$ref": "#/$defs/md"}}},
            },
            "name": {"type": "string"},
        },
    }
    data = {"body": "a", "items": [{"note": "b"}], "name": "c"}
    # 実行
    result = markdown_values(data, schema)
    # 検証
    assert result == {"body": "a", "items[0].note": "b"}


def test_markdown_values_when_any_of() -> None:
    """anyOf の中のキー（正常系）。"""
    # 準備
    schema = {
        "type": "object",
        "properties": {
            "body": {
                "anyOf": [
                    {"type": "string", "contentMediaType": "text/markdown"},
                    {"type": "null"},
                ]
            }
        },
    }
    # 実行
    result = markdown_values({"body": "a"}, schema)
    # 検証
    assert result == {"body": "a"}


@pytest.mark.parametrize(
    "data",
    [pytest.param({"body": 1}, id="not_string"), pytest.param({}, id="missing")],
)
def test_markdown_values_when_not_string(data: dict[str, Any]) -> None:
    """文字列でない値と無い値（正常系）。"""
    # 準備
    schema = {"type": "object", "properties": {"body": MARKDOWN}}
    # 実行
    result = markdown_values(data, schema)
    # 検証
    assert result == {}


def test_changed_markdown() -> None:
    """変えた値だけ（正常系）。"""
    # 準備
    previous = {"body": "a", "lead": "x"}
    data = {"body": "b", "lead": "x"}
    # 実行
    result = changed_markdown(data, previous, BODY_LEAD_SCHEMA)
    # 検証
    assert result == {"body": "b"}


def test_changed_markdown_when_create() -> None:
    """新しい文書（正常系）。"""
    # 準備
    data = {"body": "b", "lead": "x"}
    # 実行
    result = changed_markdown(data, None, BODY_LEAD_SCHEMA)
    # 検証
    assert result == {"body": "b", "lead": "x"}


def test_check_markdown_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """書き方の警告だけを違反にする（正常系）。"""
    # 準備
    findings = [
        MdmarkFinding(line=3, kind="diagram_invalid", message="A"),
        MdmarkFinding(line=1, kind="unknown_mark", message="B"),
    ]

    def fake_check(text: str, **kwargs: Any) -> object:
        return findings

    monkeypatch.setattr(markdown_module, "check_markdown", fake_check)
    # 実行
    result = check_markdown_values({"body": "x"}, cwd=tmp_path, timeout_sec=10)
    # 検証
    assert result.violations == [
        Violation(path="body", rule="mdmark の diagram_invalid（3 行目）", fix="A")
    ]
    assert result.unchecked == []
    assert result.stopped is None


def test_check_markdown_values_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI が無いと残りを呼ばない（正常系）。"""
    # 準備
    calls: list[str] = []

    def _fake(text: str, **kwargs: Any) -> list[MdmarkFinding]:
        calls.append(text)
        raise MdmarkUnavailableError(reason="R", continuable=False)

    monkeypatch.setattr(markdown_module, "check_markdown", _fake)
    # 実行
    result = check_markdown_values({"a": "x", "b": "y"}, cwd=tmp_path, timeout_sec=10)
    # 検証
    assert result.unchecked == [
        UncheckedKey(path="a", reason="R"),
        UncheckedKey(path="b", reason="R"),
    ]
    assert result.stopped == "R"
    assert calls == ["x"]


def test_check_markdown_values_when_continuable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1 つの値だけ結果を出さない（正常系）。"""
    # 準備
    calls: list[str] = []

    def _fake(text: str, **kwargs: Any) -> list[MdmarkFinding]:
        calls.append(text)
        if text == "x":
            raise MdmarkUnavailableError(reason="R", continuable=True)
        return []

    monkeypatch.setattr(markdown_module, "check_markdown", _fake)
    # 実行
    result = check_markdown_values({"a": "x", "b": "y"}, cwd=tmp_path, timeout_sec=10)
    # 検証
    assert result.unchecked == [UncheckedKey(path="a", reason="R")]
    assert result.stopped is None
    assert calls == ["x", "y"]


def test_check_markdown_values_when_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """前の文書で止めた（正常系）。"""
    # 準備
    calls: list[str] = []

    def _fake(text: str, **kwargs: Any) -> list[MdmarkFinding]:
        calls.append(text)
        return []

    monkeypatch.setattr(markdown_module, "check_markdown", _fake)
    # 実行
    result = check_markdown_values({"a": "x"}, cwd=tmp_path, timeout_sec=10, stopped="R")
    # 検証
    assert result.unchecked == [UncheckedKey(path="a", reason="R")]
    assert calls == []

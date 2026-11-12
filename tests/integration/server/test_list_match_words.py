from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


def test_normal(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    alias_file_set: Callable[..., dict[str, str]],
) -> None:
    """alias_type を持つ行の文書の name と aliases を、指す文書の ID とともに返す（正常系）。"""
    # 準備
    sample = make_source("sample", alias_file_set(broken=True))
    env = make_server(sample)
    # 実行
    result = env.call("list_match_words", cwd=str(sample.folder), source="sample", format="json")
    # 検証
    words = [(item["word"], item["id"], item["kind"]) for item in result.data["words"]]
    assert not result.is_error
    assert ("作業範囲", "scope", "name") in words
    assert ("scope", "scope", "alias") in words
    assert ("担当範囲", "scope", "alias") in words
    assert "壊れた用語" not in {item["word"] for item in result.data["words"]}


def test_normal_when_no_alias_type(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """alias_type を持つ行が無い配信元は空の一覧を返す（正常系）。"""
    # 準備
    plain = make_source("plain")
    env = make_server(plain)
    # 実行
    result = env.call("list_match_words", cwd=str(plain.folder), source="plain", format="json")
    # 検証
    assert not result.is_error
    assert not result.data.get("words")


def test_error_when_source_not_readable(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    alias_file_set: Callable[..., dict[str, str]],
) -> None:
    """cwd が scope に当たらない配信元を断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    other = make_source("other", alias_file_set())
    env = make_server(sample, other)
    # 実行
    result = env.call("list_match_words", cwd=str(sample.folder), source="other")
    # 検証
    assert result.is_error
    assert "SourceNotReadableError" in result.text
    assert "other" in result.text
    assert "sample" in result.text
    assert "担当範囲" not in result.text


def test_error_when_source_not_served(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """起動時の検証で外した配信元を断る（異常系）。"""
    # 準備
    sample = make_source("sample")
    off = make_source("off", enabled=False, scope_read=[sample.folder])
    env = make_server(sample, off)
    # 実行
    result = env.call("list_match_words", cwd=str(sample.folder), source="off")
    # 検証
    assert result.is_error
    assert "SourceNotServedError" in result.text

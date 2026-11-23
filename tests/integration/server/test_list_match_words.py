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


def test_normal_when_sqlite_rows(
    make_source: Callable[..., Any], make_server: Callable[..., Any]
) -> None:
    """alias_type を持つ SQLite の表の行の文書の名前と別名を返却する（正常系）。"""
    from tests.integration.server.conftest import sqlite_files, write_notes_db

    # 準備
    sample = make_source("sample", sqlite_files())
    write_notes_db(sample.folder)
    env = make_server(sample)
    # 実行
    result = env.call("list_match_words", cwd=str(sample.folder), source="sample", format="json")
    # 検証
    words = [(item["word"], item["id"], item["kind"]) for item in result.data["words"]]
    assert ("ゲーム実況 1", "n1", "name") in words
    assert ("実況", "n1", "alias") in words
    assert ("雑談 1", "n2", "name") in words


ASSETS_ROW = (
    "  - id: assets\n"
    "    paths: [assets/*.yaml]\n"
    "    schema: schemas/sample.schema.yaml\n"
    "    metadata: {status: state, name: title, description: summary}\n"
    "    alias_type: term\n"
    "    search_exclude: {field: status, op: eq, values: [inactive]}\n"
)


def test_normal_when_search_excluded(
    make_source: Callable[..., Any],
    make_server: Callable[..., Any],
    sample_file_set: Callable[..., dict[str, str]],
    sample_config_text: Callable[..., str],
) -> None:
    """行の search_exclude に該当する文書の単語を既定の結果から除き、include_excluded: true のときだけ excluded: true を付けて返却する（正常系）。"""
    # 準備
    files = sample_file_set(
        **{
            "project-index.yaml": sample_config_text(ASSETS_ROW),
            "assets/a1.yaml": (
                "id: a1\ntitle: アセット1\nsummary: 使用中のアセット\nstate: active\n"
            ),
            "assets/a2.yaml": (
                "id: a2\ntitle: アセット2\nsummary: 使用しなくなったアセット\nstate: inactive\n"
            ),
        }
    )
    sample = make_source("sample", files)
    env = make_server(sample)
    cwd = str(sample.folder)
    # 実行
    default = env.call("list_match_words", cwd=cwd, source="sample", format="json")
    included = env.call(
        "list_match_words", cwd=cwd, source="sample", include_excluded=True, format="json"
    )
    markdown = env.call("list_match_words", cwd=cwd, source="sample", include_excluded=True)
    # 検証
    assert not default.is_error
    assert [(item["word"], item["id"]) for item in default.data["words"]] == [("アセット1", "a1")]
    assert default.data["excluded_count"] == 1
    assert [(item["word"], item.get("excluded")) for item in included.data["words"]] == [
        ("アセット1", None),
        ("アセット2", True),
    ]
    assert "excluded_count" not in included.data
    assert "| 単語 | 文書 | 種類 | 除外 |" in markdown.text
    assert "| アセット2 | a2 | name | ✓ |" in markdown.text

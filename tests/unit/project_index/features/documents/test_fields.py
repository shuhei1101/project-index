from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from project_index.features.documents import fields as fields_module
from project_index.features.documents.fields import (
    delete_field,
    get_field,
    parse_field_path,
    resolve_metadata,
    set_field,
)
from project_index.features.sources.types import DocumentTable
from project_index.shared.errors import InvalidArgumentError

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.documents.types import Document


def test_parse_field_path() -> None:
    """キーと位置（正常系）。"""
    # 実行
    result = parse_field_path("a.b[0][1].c")
    # 検証
    assert result == ["a", "b", 0, 1, "c"]


@pytest.mark.parametrize(
    "path", [pytest.param("a..b", id="empty-key"), pytest.param("a[x-y]", id="bad-index")]
)
def test_parse_field_path_when_invalid(path: str) -> None:
    """空のキーと数字でない位置（異常系）。"""
    # 実行・検証
    with pytest.raises(InvalidArgumentError) as exc_info:
        parse_field_path(path)
    assert exc_info.value.violations[0].path == path


def test_parse_field_path_when_selector() -> None:
    """全ての要素と真偽値のキーで選ぶ要素（正常系）。"""
    from project_index.features.documents.fields import ArraySelector

    # 実行
    results = [parse_field_path("tags[].name"), parse_field_path("tags[main].name")]
    # 検証
    assert results == [
        ["tags", ArraySelector(key=None), "name"],
        ["tags", ArraySelector(key="main"), "name"],
    ]


def test_get_field() -> None:
    """入れ子と位置（正常系）。"""
    # 準備
    data = {"a": {"b": [{"c": 1}]}}
    # 実行
    result = get_field(data, "a.b[0].c")
    # 検証
    assert result == 1


@pytest.mark.parametrize("path", ["a.x", "a.b[3].c", "a.b.c"])
def test_get_field_when_missing(path: str) -> None:
    """たどれない（正常系）。"""
    # 準備
    data = {"a": {"b": [{"c": 1}]}}
    # 実行
    result = get_field(data, path)
    # 検証
    assert result is None


def test_get_field_when_selector() -> None:
    """要素を選んで取り出す（正常系）。"""
    # 準備
    data = {"tags": [{"name": "a", "main": True}, {"name": "b"}, "c"]}
    # 実行
    results = [
        get_field(data, "tags[].name"),
        get_field(data, "tags[main].name"),
        get_field({"tags": "x"}, "tags[].name"),
    ]
    # 検証
    assert results == [["a", "b"], ["a"], None]


def test_set_field() -> None:
    """途中の辞書を作る（正常系）。"""
    # 準備
    data: dict[str, Any] = {}
    # 実行
    set_field(data, "a.b.c", 1)
    # 検証
    assert data == {"a": {"b": {"c": 1}}}


def test_set_field_when_append() -> None:
    """末尾へ追加（正常系）。"""
    # 準備
    data: dict[str, Any] = {"a": [1]}
    # 実行
    set_field(data, "a[1]", 2)
    # 検証
    assert data == {"a": [1, 2]}


def test_set_field_when_type_mismatch() -> None:
    """途中が文字列（異常系）。"""
    # 準備
    data: dict[str, Any] = {"a": "x"}
    # 実行・検証
    with pytest.raises(InvalidArgumentError):
        set_field(data, "a.b", 1)


def test_set_field_when_out_of_range() -> None:
    """飛んだ位置（異常系）。"""
    # 準備
    data: dict[str, Any] = {"a": [1]}
    # 実行・検証
    with pytest.raises(InvalidArgumentError):
        set_field(data, "a[3]", 2)


def test_set_field_when_selector() -> None:
    """要素の選び方を含むパス（異常系）。"""
    # 準備
    data: dict[str, Any] = {"tags": []}
    # 実行・検証
    with pytest.raises(InvalidArgumentError, match="を含む項目のパスには書き込めません"):
        set_field(data, "tags[].name", "a")


def test_delete_field() -> None:
    """キーと位置（正常系）。"""
    # 準備
    data: dict[str, Any] = {"a": {"b": 1}, "c": [1, 2]}
    # 実行
    key_deleted = delete_field(data, "a.b")
    index_deleted = delete_field(data, "c[0]")
    # 検証
    assert key_deleted is True
    assert index_deleted is True
    assert data == {"a": {}, "c": [2]}


def test_delete_field_when_missing() -> None:
    """無い値（正常系）。"""
    # 準備
    data: dict[str, Any] = {}
    # 実行
    result = delete_field(data, "a.b")
    # 検証
    assert result is False
    assert data == {}


def test_resolve_metadata() -> None:
    """列名の対応と同じ名前の列（正常系）。"""
    # 準備
    table = DocumentTable(
        id="rules",
        paths=["docs/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"name": "title"},
        alias_type="term",
    )
    data = {"id": "a", "title": "A", "tags": ["x"]}
    # 実行
    result = resolve_metadata(data, table)
    # 検証
    assert result == {"id": "a", "name": "A", "tags": ["x"], "alias_type": "term"}


def test_resolve_metadata_when_nested_field() -> None:
    """入れ子の列（正常系）。"""
    # 準備
    table = DocumentTable(
        id="rules",
        paths=["docs/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"description": "meta.summary"},
    )
    data = {"meta": {"summary": "s"}}
    # 実行
    result = resolve_metadata(data, table)
    # 検証
    assert result["description"] == "s"


def test_resolve_metadata_when_object_array() -> None:
    """オブジェクトの配列のタグ（正常系）。"""
    # 準備
    table = DocumentTable(
        id="rules",
        paths=["docs/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"tags": "tags[].name", "main_tags": "tags[main].name"},
    )
    data = {"tags": [{"name": "mcp", "main": True}, {"name": "設計"}]}
    # 実行
    result = resolve_metadata(data, table)
    # 検証
    assert result["tags"] == ["mcp", "設計"]
    assert result["main_tags"] == ["mcp"]


def test_missing_ref_fields() -> None:
    """metadata に書いた列だけを数える（正常系）。"""
    # 準備
    table = DocumentTable(
        id="rules",
        paths=["docs/*.yaml"],
        schema_path="schemas/rule.schema.yaml",
        metadata={"name": "title", "description": "summary"},
    )
    data = {"summary": "s"}
    # 実行
    result = fields_module.missing_ref_fields(data, table)
    # 検証
    assert result == [("name", "title")]


@pytest.mark.parametrize(
    ("body_path", "expected"),
    [
        pytest.param("docs/a.md", True, id="markdown"),
        pytest.param("docs/B.MD", True, id="upper-case"),
        pytest.param("src/a.py", False, id="source-code"),
        pytest.param(None, False, id="no-body-file"),
    ],
)
def test_is_markdown_body(
    make_document: Callable[..., Document], body_path: str | None, expected: bool
) -> None:
    """本文のファイルの拡張子（正常系）。"""
    # 準備
    from project_index.features.documents.fields import is_markdown_body

    document = make_document(path="docs/x.md", body_path=body_path)
    # 実行
    result = is_markdown_body(document)
    # 検証
    assert result is expected


def test_unresolved_related() -> None:
    """source を持たない関連だけを照合する（正常系）。"""
    # 準備
    metadata = {
        "related": [
            {"to": "src/b.py"},
            {"to": "src/z.py"},
            {"to": "other-doc", "source": "other"},
            {"to": "src/y.py", "source": None},
            {"type": "tests"},
        ]
    }
    ids = {"src/a.py", "src/b.py"}
    # 実行
    result = fields_module.unresolved_related(metadata, ids)
    # 検証
    assert result == ["src/z.py", "src/y.py"]


def test_unresolved_related_when_not_list() -> None:
    """related が配列でない（正常系）。"""
    # 準備
    ids = {"src/a.py"}
    # 実行
    missing = fields_module.unresolved_related({"name": "a"}, ids)
    text = fields_module.unresolved_related({"related": "src/z.py"}, ids)
    # 検証
    assert missing == []
    assert text == []

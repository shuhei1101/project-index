from __future__ import annotations

from typing import TYPE_CHECKING

from project_index.features.search.fields import field_values, heading_lines, known_fields
from project_index.features.search.types import Heading

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.features.documents.types import Document


def test_field_values(make_document: Callable[..., Document]) -> None:
    """項目の種類ごとの値（正常系）。"""
    # 準備
    document = make_document(
        metadata={"tags": ["a", "b"]},
        data={"owner": {"name": "x"}},
        body="# 見出し",
    )
    # 実行
    tags = field_values(document, "tags")
    owner = field_values(document, "owner.name")
    chars = field_values(document, "@chars")
    missing = field_values(document, "missing")
    # 検証
    assert tags == ["a", "b"]
    assert owner == ["x"]
    assert chars == [5]
    assert missing == []


def test_heading_lines() -> None:
    """階層とコードブロック（正常系）。"""
    # 準備
    lines = ["# a", "", "## b ##", "```", "## c", "```", "### d"]
    # 実行
    result = heading_lines(lines)
    # 検証
    assert result == [
        Heading(line=1, level=1, text="a"),
        Heading(line=3, level=2, text="b"),
        Heading(line=7, level=3, text="d"),
    ]


def test_field_values_when_columns(make_document: Callable[..., Document]) -> None:
    """行の metadata で対応付けた列の値（正常系）。"""
    # 準備
    document = make_document(metadata={"name": "a"}, data={"section": "使い方", "title": "b"})
    columns = {"category": "section", "name": "title"}
    # 実行
    category = field_values(document, "category", columns=columns)
    name = field_values(document, "name", columns=columns)
    # 検証
    assert category == ["使い方"]
    assert name == ["a"]


def test_with_metadata_fields() -> None:
    """対応付けた列の型で加える（正常系）。"""
    from project_index.features.search.fields import with_metadata_fields
    from project_index.features.sources.types import DocumentTable

    # 準備
    fields = {"name": "string", "section": "string", "labels": "array"}
    row = DocumentTable(
        id="guide",
        paths=["guide/files.yaml"],
        schema_path="schemas/files.schema.yaml",
        metadata={
            "category": "section",
            "kinds": "labels",
            "area": "meta.area",
            "all": "**.section",
            "name": "title",
        },
    )
    row_fields = {"section": "string", "labels": "array"}
    # 実行
    result = with_metadata_fields(fields, [(row, row_fields)])
    # 検証
    assert result == {
        "name": "string",
        "section": "string",
        "labels": "array",
        "category": "string",
        "kinds": "array",
        "area": "string",
        "all": "string",
    }
    assert fields == {"name": "string", "section": "string", "labels": "array"}


def test_with_metadata_fields_when_rows_differ() -> None:
    """行ごとに型が食い違うキーと他の行のスキーマ（正常系）。"""
    from project_index.features.search.fields import with_metadata_fields
    from project_index.features.sources.types import DocumentTable

    # 準備
    fields = {"section": "number", "labels": "array"}
    row_a = DocumentTable(
        id="guide",
        paths=["guide/files.yaml"],
        schema_path="schemas/guide.schema.yaml",
        metadata={"order": "section"},
    )
    row_b = DocumentTable(
        id="api",
        paths=["api/*.yaml"],
        schema_path="schemas/api.schema.yaml",
        metadata={"order": "labels"},
    )
    # 実行
    result = with_metadata_fields(
        fields, [(row_a, {}), (row_b, {"section": "number", "labels": "array"})]
    )
    # 検証
    assert result["order"] == "string"


def test_field_values_when_array_item_keys(make_document: Callable[..., Document]) -> None:
    """配列の中のオブジェクトのキーの値（正常系）。"""
    # 準備
    document = make_document(data={"uses": [{"id": "compare"}, {"id": "list"}, {"name": "x"}]})
    # 実行
    result = field_values(document, "uses[].id")
    # 検証
    assert result == ["compare", "list"]


def test_known_fields_when_array_items() -> None:
    """配列の中のオブジェクトのキー（正常系）。"""
    # 準備
    schema = {
        "type": "object",
        "properties": {
            "uses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "refs": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"to": {"type": "string"}},
                            },
                        },
                    },
                },
            },
            "category": {"type": "object", "properties": {"id": {"type": "string"}}},
        },
    }
    # 実行
    fields = known_fields([schema])
    # 検証
    assert fields["uses"] == "array"
    assert fields["uses[].id"] == "string"
    assert fields["uses[].refs[].to"] == "string"
    assert fields["category.id"] == "string"
    assert "uses.id" not in fields
    assert "uses.refs.to" not in fields

from __future__ import annotations

from project_index.features.validation.rules import (
    check_id_format,
    check_related,
    check_schema,
)

DEFAULT_TYPES = ["references", "depends_on", "see_also"]


def test_check_schema() -> None:
    """合格（正常系）。"""
    # 準備
    schema = {"type": "object", "required": ["id"]}
    # 実行
    result = check_schema({"id": "a"}, schema, schema_file="schemas/note.schema.yaml")
    # 検証
    assert result == []


def test_check_schema_when_violations() -> None:
    """違反のパスと直し方（正常系）。"""
    # 準備
    schema = {
        "type": "object",
        "required": ["id"],
        "properties": {"items": {"type": "array", "items": {"type": "integer"}}},
    }
    # 実行
    result = check_schema({"items": [1, "x"]}, schema, schema_file="schemas/note.schema.yaml")
    # 検証
    assert [violation.path for violation in result] == ["$", "items[1]"]
    assert "id" in result[0].fix
    assert "integer" in result[1].fix


def test_check_schema_when_unresolvable() -> None:
    """解決できない参照（正常系）。"""
    # 準備
    schema = {"properties": {"a": {"$ref": "missing.schema.yaml#/$defs/x"}}}
    # 実行
    result = check_schema({"a": 1}, schema, schema_file="schemas/note.schema.yaml")
    # 検証
    assert [violation.path for violation in result] == ["$"]
    assert "missing.schema.yaml#/$defs/x" in result[0].rule
    assert "schemas/note.schema.yaml" in result[0].rule


def test_check_schema_when_empty() -> None:
    """スキーマが無い（正常系）。"""
    # 実行
    result = check_schema({"anything": 1}, {}, schema_file="schemas/note.schema.yaml")
    # 検証
    assert result == []


def test_check_id_format() -> None:
    """合う ID（正常系）。"""
    # 実行
    result = check_id_format("rule-python-testing", "{kind}-{slug}", kind="rule")
    # 検証
    assert result == []


def test_check_id_format_when_mismatch() -> None:
    """合わない ID（正常系）。"""
    # 実行
    result = check_id_format("Python_Testing", "{kind}-{slug}", kind="rule")
    # 検証
    assert len(result) == 1
    assert result[0].path == "id"
    assert result[0].rule == "ids.format"


def test_check_id_format_when_none() -> None:
    """制約なし（正常系）。"""
    # 実行
    result = check_id_format("Any_ID", None, kind="rule")
    # 検証
    assert result == []


def test_check_related() -> None:
    """知らない種類（正常系）。"""
    # 準備
    metadata = {"related": [{"to": "a", "type": "references"}, {"to": "b", "type": "blocks"}]}
    # 実行
    result = check_related(metadata, DEFAULT_TYPES)
    # 検証
    assert len(result) == 1
    assert result[0].path == "related[1].type"
    assert "references, depends_on, see_also" in result[0].fix


def test_check_related_when_malformed() -> None:
    """行の形の誤り（正常系）。"""
    # 準備
    metadata = {"related": ["a", {"type": "references"}]}
    # 実行
    result = check_related(metadata, DEFAULT_TYPES)
    # 検証
    assert [violation.path for violation in result] == ["related[0]", "related[1].to"]

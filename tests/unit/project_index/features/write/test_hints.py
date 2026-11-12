from __future__ import annotations

from project_index.features.validation.rules import check_id_format, check_schema
from project_index.features.write.hints import attach_schema_hints
from project_index.shared.errors import Violation

SCHEMA = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {
            "type": "string",
            "title": "名前",
            "description": "文書の名前",
            "examples": ["設定のリファレンス"],
        },
        "count": {"type": "integer"},
        "status": {
            "type": "string",
            "x-rules": ["current か draft にする"],
            "x-bad-examples": ["済"],
        },
    },
}


def test_attach_schema_hints() -> None:
    """違反した項目の説明だけを添える（正常系）。"""
    # 準備
    data = {"count": "3"}
    violations = check_schema(data, SCHEMA)
    # 実行
    result = attach_schema_hints(violations, schema=SCHEMA, data=data)
    # 検証
    assert [(item.path, item.schema) for item in result] == [
        ("$", {"title": "名前", "description": "文書の名前", "examples": ["設定のリファレンス"]}),
        ("count", None),
    ]


def test_attach_schema_hints_when_rules() -> None:
    """`x-rules`・`x-bad-examples` も添える（正常系）。"""
    # 準備
    data = {"name": "a", "status": 1}
    violations = check_schema(data, SCHEMA)
    # 実行
    result = attach_schema_hints(violations, schema=SCHEMA, data=data)
    # 検証
    assert [item.schema for item in result] == [
        {"x-rules": ["current か draft にする"], "x-bad-examples": ["済"]}
    ]


def test_attach_schema_hints_when_not_schema() -> None:
    """スキーマの違反でないものには添えない（正常系）。"""
    # 準備
    data = {"name": "a"}
    violations = [
        *check_id_format("x", "{kind}-{slug}", kind="rule"),
        Violation(path="name", rule="validator-rule"),
    ]
    # 実行
    result = attach_schema_hints(violations, schema=SCHEMA, data=data)
    # 検証
    assert [(item.path, item.schema) for item in result] == [("id", None), ("name", None)]

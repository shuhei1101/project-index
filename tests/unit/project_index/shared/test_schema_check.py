from __future__ import annotations

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from project_index.shared.errors import Violation
from project_index.shared.schema_check import _as_list, _from_error, format_path, schema_violations


def test_format_path() -> None:
    """キーと添字をつなぐ（正常系）。"""
    # 準備
    parts: list[str | int] = ["sources", 0, "config"]
    # 実行
    result = format_path(parts)
    # 検証
    assert result == "sources[0].config"


def test_format_path_when_index_first() -> None:
    """先頭が添字（正常系）。"""
    # 準備
    parts: list[str | int] = [0, "id"]
    # 実行
    result = format_path(parts)
    # 検証
    assert result == "[0].id"


def test_format_path_when_empty() -> None:
    """空の並び（正常系）。"""
    # 準備
    parts: list[str | int] = []
    # 実行
    result = format_path(parts)
    # 検証
    assert result == ""


def test_as_list() -> None:
    """配列の要素を文字列にする（正常系）。"""
    # 準備
    value = ["a", 1]
    # 実行
    result = _as_list(value)
    # 検証
    assert result == ["a", "1"]


def test_as_list_when_not_list() -> None:
    """配列でない（正常系）。"""
    # 準備
    value = "a"
    # 実行
    result = _as_list(value)
    # 検証
    assert result == []


def test_from_error_when_required() -> None:
    """必須のキーが無い誤りは無いキーごと（正常系）。"""
    # 準備
    schema = {"properties": {"s": {"required": ["a", "b"]}}}
    [error] = Draft202012Validator(schema).iter_errors({"s": {"a": 1}})
    # 実行
    result = _from_error(error)
    # 検証
    assert result == [Violation(path="s.b", rule="必須のキーが無い")]


def test_from_error_when_additional_properties() -> None:
    """知らないキーの誤りはキーごと（正常系）。"""
    # 準備
    schema = {"properties": {"a": {}}, "additionalProperties": False}
    [error] = Draft202012Validator(schema).iter_errors({"a": 1, "x": 2})
    # 実行
    result = _from_error(error)
    # 検証
    assert result == [Violation(path="x", rule="知らないキー")]


def test_from_error_when_type() -> None:
    """型の誤り（正常系）。"""
    # 準備
    schema = {"properties": {"a": {"type": "string"}}}
    [error] = Draft202012Validator(schema).iter_errors({"a": 1})
    # 実行
    result = _from_error(error)
    # 検証
    assert result == [Violation(path="a", rule="型が違う（期待: string）")]


def test_from_error_when_enum() -> None:
    """列挙の誤り（最上位）（正常系）。"""
    # 準備
    schema = {"enum": ["x", "y"]}
    [error] = Draft202012Validator(schema).iter_errors("z")
    # 実行
    result = _from_error(error)
    # 検証
    assert result == [Violation(path="$", rule="次のどれかにする: ['x', 'y']")]


def test_from_error_when_other() -> None:
    """その他の誤りは誤りの message（正常系）。"""
    # 準備
    schema = {"minimum": 1}
    [error] = Draft202012Validator(schema).iter_errors(0)
    # 実行
    result = _from_error(error)
    # 検証
    assert result == [Violation(path="$", rule="0 is less than the minimum of 1")]


def test_schema_violations() -> None:
    """違反が無い（正常系）。"""
    # 準備
    schema = {"type": "object"}
    # 実行
    result = schema_violations(schema, {})
    # 検証
    assert result == []


def test_schema_violations_when_many() -> None:
    """違反を全て集め、項目のパスの順に並べる（正常系）。"""
    # 準備
    schema = {"properties": {"a": {"type": "string"}, "b": {"type": "string"}}}
    # 実行
    result = schema_violations(schema, {"b": 1, "a": 1})
    # 検証
    assert [violation.path for violation in result] == ["a", "b"]


def test_schema_violations_when_registry() -> None:
    """別のファイルを `$ref` で指すスキーマ（正常系）。"""
    # 準備
    common = Resource.from_contents(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"name": {"type": "string"}},
        }
    )
    registry: Registry[object] = Registry().with_resource("common.json", common)
    schema = {"$ref": "common.json#/$defs/name"}
    # 実行
    result = schema_violations(schema, 1, registry=registry)
    # 検証
    assert result == [Violation(path="$", rule="型が違う（期待: string）")]

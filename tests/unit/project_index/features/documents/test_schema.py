from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for

from project_index.features.documents import schema as schema_module
from project_index.features.documents.schema import resolve_schema_refs, startup_schema
from project_index.features.sources.schema_ref import SchemaRef
from project_index.features.sources.types import DocumentTable, ServedSource, SourceConfig
from project_index.shared.yaml_io import load_yaml as load_yaml_value

if TYPE_CHECKING:
    from collections.abc import Callable


def load_yaml(text: str) -> Any:
    """形の分かっている YAML の文字列を読む。"""
    return load_yaml_value(text)


FILES_SCHEMA_TEMPLATE = Path(__file__).parents[5] / "templates" / "files.schema.yaml"

COMMON_SCHEMA = "$defs:\n  markdown:\n    type: string\n    title: Markdown\n"


def test_resolve_schema_refs(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """同じファイルと別のファイルの参照（正常系）。"""
    # 準備
    write_files(tmp_path, {"schemas/共通.schema.yaml": COMMON_SCHEMA})
    schema = {
        "$defs": {"x": {"type": "integer"}},
        "properties": {
            "a": {"$ref": "#/$defs/x"},
            "b": {"$ref": "共通.schema.yaml#/$defs/markdown", "title": "B"},
        },
    }
    # 実行
    result = resolve_schema_refs(schema, tmp_path / "schemas" / "rule.schema.yaml")
    # 検証
    assert result["properties"]["a"] == {"type": "integer"}
    assert result["properties"]["b"] == {"type": "string", "title": "B"}


def test_resolve_schema_refs_when_cycle(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """循環する参照（正常系）。"""
    # 準備
    schema = {
        "$defs": {
            "node": {
                "type": "object",
                "properties": {"children": {"items": {"$ref": "#/$defs/node"}}},
            }
        },
        "properties": {"root": {"$ref": "#/$defs/node"}},
    }
    # 実行
    with caplog.at_level(logging.WARNING):
        result = resolve_schema_refs(schema, tmp_path / "rule.schema.yaml")
    # 検証
    children = result["properties"]["root"]["properties"]["children"]
    assert children["items"] == {"$ref": "#/$defs/node"}
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_resolve_schema_refs_when_relative_ref_in_defs(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """`$defs` の中の相対パスの参照と循環する参照（正常系）。"""
    # 準備
    write_files(tmp_path, {"schemas/共通.schema.yaml": "$defs:\n  summary:\n    type: string\n"})
    schema = {
        "$defs": {
            "entry": {
                "type": "object",
                "properties": {
                    "summary": {"$ref": "共通.schema.yaml#/$defs/summary"},
                    "children": {"type": "array", "items": {"$ref": "#/$defs/entry"}},
                },
            }
        },
        "properties": {"entries": {"type": "array", "items": {"$ref": "#/$defs/entry"}}},
    }
    # 実行
    result = resolve_schema_refs(schema, tmp_path / "schemas" / "layout.schema.yaml")
    # 検証
    entry = result["$defs"]["entry"]["properties"]
    assert entry["summary"] == {"type": "string"}
    assert entry["children"]["items"] == {"$ref": "#/$defs/entry"}
    assert result["properties"]["entries"]["items"]["properties"]["summary"] == {"type": "string"}
    assert "共通.schema.yaml" not in repr(result)


TREE_SCHEMA = (
    "$defs:\n"
    "  tree:\n"
    "    type: object\n"
    "    properties:\n"
    "      name:\n"
    "        type: string\n"
    "      children:\n"
    "        type: array\n"
    "        items:\n"
    "          $ref: '#/$defs/tree'\n"
)


def test_resolve_schema_refs_when_cycle_in_other_file(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """別のファイルの中で循環する参照（正常系）。"""
    # 準備
    write_files(tmp_path, {"schemas/共通.schema.yaml": TREE_SCHEMA})
    schema = {"properties": {"tree": {"$ref": "共通.schema.yaml#/$defs/tree"}}}
    value = {"tree": {"name": "a", "children": [{"name": "b", "children": [{"name": "c"}]}]}}
    # 実行
    with caplog.at_level(logging.WARNING):
        result = resolve_schema_refs(schema, tmp_path / "schemas" / "rule.schema.yaml")
    # 検証
    # `共通.schema.yaml#/$defs/tree` を JSON Pointer の区切りとしてエスケープし、URL エンコードした名前を指す
    hoisted_ref = {"$ref": "#/$defs/%E5%85%B1%E9%80%9A.schema.yaml%23~1%24defs~1tree"}
    hoisted = result["$defs"]["共通.schema.yaml#/$defs/tree"]
    assert hoisted["properties"]["children"]["items"] == hoisted_ref
    assert result["properties"]["tree"]["properties"]["children"]["items"] == hoisted_ref
    assert (
        list(validator_for(result, default=Draft202012Validator)(result).iter_errors(value)) == []
    )
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_resolve_schema_refs_when_cycle_in_other_file_with_same_name(
    tmp_path: Path, write_files: Callable[[Path, dict[str, str]], None]
) -> None:
    """別のファイルの中で循環する参照と同じ名前の定義（正常系）。"""
    # 準備
    write_files(tmp_path, {"schemas/共通.schema.yaml": TREE_SCHEMA})
    schema = {
        "$defs": {"tree": {"type": "string"}, "共通.schema.yaml#/$defs/tree": {"type": "integer"}},
        "properties": {"tree": {"$ref": "共通.schema.yaml#/$defs/tree"}},
    }
    value = {"tree": {"name": "a", "children": [{"name": "b", "children": [{"name": "c"}]}]}}
    # 実行
    result = resolve_schema_refs(schema, tmp_path / "schemas" / "rule.schema.yaml")
    # 検証
    hoisted_ref = {"$ref": "#/$defs/%E5%85%B1%E9%80%9A.schema.yaml%23~1%24defs~1tree-2"}
    assert result["$defs"]["tree"] == {"type": "string"}
    assert result["$defs"]["共通.schema.yaml#/$defs/tree"] == {"type": "integer"}
    hoisted = result["$defs"]["共通.schema.yaml#/$defs/tree-2"]
    assert hoisted["properties"]["children"]["items"] == hoisted_ref
    assert result["properties"]["tree"]["properties"]["children"]["items"] == hoisted_ref
    assert (
        list(validator_for(result, default=Draft202012Validator)(result).iter_errors(value)) == []
    )


def test_resolve_schema_refs_when_missing(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """参照先が無い（正常系）。"""
    # 準備
    schema = {"properties": {"a": {"$ref": "無い.schema.yaml#/$defs/x"}}}
    # 実行
    with caplog.at_level(logging.WARNING):
        result = resolve_schema_refs(schema, tmp_path / "rule.schema.yaml")
    # 検証
    assert result["properties"]["a"] == {"$ref": "無い.schema.yaml#/$defs/x"}
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_resolve_schema_refs_when_read(caplog: pytest.LogCaptureFixture) -> None:
    """読み取りの関数で参照先を読む（正常系）。"""
    # 準備
    files = {"schemas/共通.schema.yaml": "$defs:\n  x:\n    type: integer\n"}
    schema = {
        "properties": {
            "a": {"$ref": "共通.schema.yaml#/$defs/x"},
            "b": {"$ref": "../../out.schema.yaml#/$defs/y"},
        }
    }
    # 実行
    with caplog.at_level(logging.WARNING):
        result = resolve_schema_refs(
            schema, PurePosixPath("schemas/note.schema.yaml"), read=files.get
        )
    # 検証
    assert result["properties"]["a"] == {"type": "integer"}
    assert result["properties"]["b"] == {"$ref": "../../out.schema.yaml#/$defs/y"}


def test_startup_schema(
    tmp_path: Path,
    write_files: Callable[[Path, dict[str, str]], None],
    make_served_source: Callable[..., ServedSource],
) -> None:
    """相対パスとほかの配信元の参照（正常系）。"""
    # 準備
    write_files(tmp_path / "sample", {"schemas/共通.schema.yaml": COMMON_SCHEMA})
    local = DocumentTable(id="local", paths=["a/*.yaml"], schema_path="schemas/rule.schema.yaml")
    remote = DocumentTable(
        id="remote",
        paths=["b/*.yaml"],
        schema_path=SchemaRef(source="schemas", path="schemas/note.schema.yaml", ref="v1"),
    )
    source = make_served_source(
        config=SourceConfig(name="sample", documents=[local, remote]),
        schemas={
            "local": {"properties": {"body": {"$ref": "共通.schema.yaml#/$defs/markdown"}}},
            "remote": {"properties": {"body": {"$ref": "keep.schema.yaml#/$defs/x"}}},
        },
    )
    # 実行
    resolved_local = startup_schema(source, local)
    resolved_remote = startup_schema(source, remote)
    # 検証
    assert resolved_local == {"properties": {"body": {"type": "string", "title": "Markdown"}}}
    assert resolved_remote == {"properties": {"body": {"$ref": "keep.schema.yaml#/$defs/x"}}}


def test_records_item_schema() -> None:
    """要素のスキーマを取り出す（正常系）。"""
    # 準備
    schema = load_yaml(FILES_SCHEMA_TEMPLATE.read_text(encoding="utf-8"))
    # 実行
    result = schema_module.records_item_schema(schema, "files")
    # 検証
    assert result is not None
    assert result["required"] == ["path"]


@pytest.mark.parametrize(
    ("schema", "records"),
    [
        pytest.param({"properties": {"files": {"type": "array"}}}, "files", id="no_items"),
        pytest.param({"type": "object"}, "files", id="no_properties"),
        pytest.param(
            {"properties": {"files": {"type": "array", "items": {"type": "object"}}}},
            "rows",
            id="other_records",
        ),
    ],
)
def test_records_item_schema_when_missing(schema: dict[str, object], records: str) -> None:
    """要素のスキーマが無い（正常系）。"""
    # 実行
    result = schema_module.records_item_schema(schema, records)
    # 検証
    assert result is None

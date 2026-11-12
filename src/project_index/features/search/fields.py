"""検索で使う項目の値と使える項目。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from project_index.features.documents.fields import METADATA_KEYS, get_field, is_markdown_body
from project_index.features.search.types import Heading
from project_index.shared.errors import InvalidArgumentError

if TYPE_CHECKING:
    from project_index.features.documents.types import Document

COMPUTED_FIELDS = ("@chars", "@path", "@sections", "@matches")
DATE_FIELDS = ("created", "updated")

ARRAY_METADATA = ("tags", "related", "aliases", "avoid")
NUMBER_METADATA = ("port",)
HEADING = re.compile(r"^\s{0,3}(?P<level>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
SCHEMA_TYPES = {"string", "number", "boolean", "array", "object"}


def _leaves(value: Any) -> list[str]:  # noqa: ANN401
    """入れ子の値から文字列の葉を集める。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item)]
    return []


def heading_lines(lines: Sequence[str]) -> list[Heading]:
    """Markdown の行の並びから、見出しの行番号・階層・文字列を集める（コードブロックの中は除く）。"""
    result: list[Heading] = []
    fenced = False
    for number, line in enumerate(lines, start=1):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and (matched := HEADING.match(line)):
            result.append(
                Heading(line=number, level=len(matched.group("level")), text=matched.group("text"))
            )
    return result


def _headings(body: str) -> list[str]:
    """Markdown の本文の見出しの文字列を集める。"""
    return [heading.text for heading in heading_lines(body.splitlines())]


def _raw_values(document: Document, field: str) -> Any:  # noqa: ANN401, C901
    """項目の値を、配列のまま引く。"""
    if field == "id":
        return document.id
    if field == "kind":
        return document.kind
    if field == "version":
        return document.version
    if field in DATE_FIELDS:
        return getattr(document, field)
    if field == "body":
        return document.body
    if field == "*":
        return [*_leaves(document.data), document.body]
    if field == "@chars":
        return len(document.body)
    if field == "@path":
        suffix = "" if document.record_index is None else f"#{document.record_index}"
        return f"{document.path}{suffix}"
    if field == "@matches":
        # 条件で決まり文書だけでは決まらないので、値を持たない（検索が当たった行の数で数える）
        return None
    if field == "@sections":
        return _headings(document.body) if is_markdown_body(document) else list(document.data)
    if field in METADATA_KEYS:
        return document.metadata.get(field)
    try:
        return get_field(document.data, field)
    except InvalidArgumentError:
        return None


def field_values(document: Document, field: str) -> list[Any]:
    """文書から項目の値を引き、比べられる値の並びにする。"""
    value = _raw_values(document, field)
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _base_fields() -> dict[str, str]:
    """スキーマに依らず使える項目と型。"""
    fields = {"id": "string", "kind": "string", "created": "date", "updated": "date"}
    for key in METADATA_KEYS:
        if key in ARRAY_METADATA:
            fields[key] = "array"
        elif key in NUMBER_METADATA:
            fields[key] = "number"
        else:
            fields[key] = "string"
    fields.update({"body": "string", "*": "string", "version": "string"})
    fields.update(
        {"@chars": "number", "@path": "string", "@sections": "array", "@matches": "number"}
    )
    return fields


def _schema_type(schema: Mapping[str, Any]) -> str:
    """スキーマの `type` と `format` から項目の型を決める。"""
    if schema.get("format") in ("date", "date-time"):
        return "date"
    declared = schema.get("type")
    if isinstance(declared, list):
        declared = next((item for item in declared if item != "null"), "string")
    if declared == "integer":
        return "number"
    return declared if declared in SCHEMA_TYPES else "string"


def _walk(schema: Mapping[str, Any], prefix: str, fields: dict[str, str]) -> None:
    """スキーマの `properties` を再帰でたどり、項目のパスと型を足す。"""
    properties = schema.get("properties")
    if isinstance(properties, Mapping):
        for key, sub in properties.items():
            if not isinstance(sub, Mapping):
                continue
            path = f"{prefix}{key}"
            declared = _schema_type(sub)
            # 型の食い違う同じパスは string にする
            fields[path] = declared if fields.get(path, declared) == declared else "string"
            _walk(sub, f"{path}.", fields)
    items = schema.get("items")
    if isinstance(items, Mapping):
        _walk(items, prefix, fields)


def known_fields(schemas: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """配信元の種類のスキーマから、条件・並べ替え・集計に使える項目の一覧を作る。"""
    fields = _base_fields()
    for schema in schemas:
        _walk(schema, "", fields)
    return fields


def as_datetime(value: Any) -> datetime | None:  # noqa: ANN401
    """日時・日付・ISO 8601 の文字列を日時にする。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day).astimezone()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None

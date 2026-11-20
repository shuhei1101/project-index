"""検索で使う項目の値と使える項目。"""

from __future__ import annotations

import re
from datetime import date, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from project_index.features.documents.fields import METADATA_KEYS, get_field, is_markdown_body
from project_index.features.search.types import Heading
from project_index.shared.errors import InvalidArgumentError
from project_index.shared.narrowing import is_dict, is_list

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from project_index.features.documents.types import Document
    from project_index.features.sources.types import DocumentTable

COMPUTED_FIELDS = ("@chars", "@path", "@sections", "@matches")
DATE_FIELDS = ("created", "updated")

ARRAY_METADATA = ("tags", "related", "aliases", "avoid")
NUMBER_METADATA = ("port",)
HEADING = re.compile(r"^\s{0,3}(?P<level>#{1,6})\s+(?P<text>.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
SCHEMA_TYPES = {"string", "number", "boolean", "array", "object"}
# 要素のスキーマを同じパスでたどる合成のキー
COMPOSITION_KEYS = ("allOf", "anyOf", "oneOf")
# 最上位の `$defs` の定義を指す `$ref` の接頭辞
DEFS_REF_PREFIX = "#/$defs/"
# 行の metadata の対応付けを指定しないときの空の対応
NO_COLUMNS: Mapping[str, str] = MappingProxyType({})


def _leaves(value: object) -> list[str]:
    """入れ子の値から文字列の葉を集める。"""
    if isinstance(value, str):
        return [value]
    if is_dict(value):
        return [leaf for item in value.values() for leaf in _leaves(item)]
    if is_list(value):
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


def _path(document: Document) -> str:
    """文書の場所（`records` の行は `{path}#{record_index}`）。"""
    suffix = "" if document.record_index is None else f"#{document.record_index}"
    return f"{document.path}{suffix}"


def _sections(document: Document) -> list[str]:
    """Markdown の本文なら見出しの文字列、それ以外は `data` の最上位のキーの並び。"""
    return _headings(document.body) if is_markdown_body(document) else list(document.data)


# 文書の属性・計算で値を決める項目（`@matches` は条件で決まり文書だけでは決まらないので値を持たない）
_COMPUTED: dict[str, Callable[[Document], object]] = {
    "id": lambda document: document.id,
    "kind": lambda document: document.kind,
    "version": lambda document: document.version,
    "created": lambda document: document.created,
    "updated": lambda document: document.updated,
    "body": lambda document: document.body,
    "*": lambda document: [*_leaves(document.data), document.body],
    "@chars": lambda document: len(document.body),
    "@path": _path,
    "@matches": lambda _: None,
    "@sections": _sections,
}


def _raw_values(document: Document, field: str, columns: Mapping[str, str]) -> object:
    """項目の値を、配列のまま引く。"""
    computed = _COMPUTED.get(field)
    if computed is not None:
        return computed(document)
    if field in METADATA_KEYS:
        return document.metadata.get(field)
    # 行の metadata で対応付けたキー: 対応付けた列から取得する（無ければ同じ名前の項目）
    path = columns.get(field, field)
    try:
        return get_field(document.data, path)
    except InvalidArgumentError:
        return None


def field_values(
    document: Document, field: str, *, columns: Mapping[str, str] = NO_COLUMNS
) -> list[Any]:
    """文書から項目の値を引き、比べられる値の並びにする。"""
    value = _raw_values(document, field, columns)
    if value is None:
        return []
    return list(value) if is_list(value) else [value]


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


def _schema_type(schema: dict[object, object]) -> str:
    """スキーマの `type` と `format` から項目の型を決める。"""
    if schema.get("format") in ("date", "date-time"):
        return "date"
    declared = schema.get("type")
    if is_list(declared):
        declared = next((item for item in declared if item != "null"), "string")
    if declared == "integer":
        return "number"
    return declared if isinstance(declared, str) and declared in SCHEMA_TYPES else "string"


def _defs_target(
    schema: dict[object, object], defs: Mapping[object, object], visiting: tuple[str, ...]
) -> tuple[str, object] | None:
    """最上位の `$defs` を指して残った `$ref` の、たどる定義の名前と中身を返却する。"""
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith(DEFS_REF_PREFIX):
        return None
    raw = ref.removeprefix(DEFS_REF_PREFIX)
    # `$defs` の定義の中をさらに指す JSON Pointer は、最上位の定義の名前でないのでたどらない
    if "/" in raw:
        return None
    # JSON Pointer の名前として URL エンコードとエスケープを戻す
    name = unquote(raw).replace("~1", "/").replace("~0", "~")
    # たどっている途中の定義へ戻る参照・`$defs` に無い名前は、たどらない
    if name in visiting or name not in defs:
        return None
    return name, defs[name]


def _walk_properties(
    properties: dict[object, object],
    prefix: str,
    fields: dict[str, str],
    defs: Mapping[object, object],
    visiting: tuple[str, ...],
) -> None:
    """`properties` のキーごとに項目のパスと型を追加し、その中をたどる。"""
    for key, sub in properties.items():
        if not is_dict(sub):
            continue
        path = f"{prefix}{key}"
        declared = _schema_type(sub)
        # 型の食い違う同じパスは string にする
        fields[path] = declared if fields.get(path, declared) == declared else "string"
        _walk(sub, f"{path}.", fields, defs, visiting)


def _walk(
    schema: object,
    prefix: str,
    fields: dict[str, str],
    defs: Mapping[object, object],
    visiting: tuple[str, ...] = (),
) -> None:
    """スキーマの `properties` を再帰でたどり、項目のパスと型を足す。"""
    if not is_dict(schema):
        return
    # 循環して最上位の `$defs` を指して残った参照は、参照先の定義を同じパスでたどる
    target = _defs_target(schema, defs, visiting)
    if target is not None:
        name, definition = target
        _walk(definition, prefix, fields, defs, (*visiting, name))
    properties = schema.get("properties")
    if is_dict(properties):
        _walk_properties(properties, prefix, fields, defs, visiting)
    # allOf・anyOf・oneOf の各要素は、それらを持つスキーマと同じパスでたどる
    for key in COMPOSITION_KEYS:
        variants = schema.get(key)
        if is_list(variants):
            for variant in variants:
                _walk(variant, prefix, fields, defs, visiting)
    # 配列の要素のキーは `a[].b` のパスにする（最上位のスキーマの `items` は `[]` を付けない）
    items_prefix = f"{prefix.removesuffix('.')}[]." if prefix else ""
    _walk(schema.get("items"), items_prefix, fields, defs, visiting)


def known_fields(schemas: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """配信元の種類のスキーマから、条件・並べ替え・集計に使える項目の一覧を作る。"""
    fields = _base_fields()
    for schema in schemas:
        # 参照先の定義は、たどっているスキーマ自身の最上位の `$defs` だけを参照する
        defs: object = schema.get("$defs")
        _walk(dict(schema), "", fields, defs if is_dict(defs) else {})
    return fields


def with_metadata_fields(
    fields: Mapping[str, str],
    rows: Iterable[tuple[DocumentTable, Mapping[str, str]]],
) -> dict[str, str]:
    """使える項目に、文書の行の `metadata` で対応付けたキーを、対応付けた列の型で加える。"""
    result = dict(fields)
    for row, row_fields in rows:
        for key, column in row.metadata.items():
            # 既に使える項目（共通のキー・スキーマの項目・先の行で加えたキー）はそのまま
            if key in result:
                continue
            # 型は、その行の使える項目の列名そのままの型（無ければ string）
            result[key] = row_fields.get(column, "string")
    return result


def as_datetime(value: object) -> datetime | None:
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

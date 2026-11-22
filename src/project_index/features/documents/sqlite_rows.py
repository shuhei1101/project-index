"""SQLite の表の行を読み取り専用で読んで文書にし、ファイルが変わったときだけ読み直す。"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ruamel.yaml.comments import CommentedMap

from project_index.features.documents.fields import resolve_metadata
from project_index.features.documents.types import Document
from project_index.shared.errors import Violation
from project_index.shared.hashing import content_hash, value_hash
from project_index.shared.yaml_io import dump_roundtrip

if TYPE_CHECKING:
    from pathlib import Path

    from project_index.features.sources.types import DocumentTable, SqliteTable

__all__ = [
    "SqliteRowCache",
    "SqliteRows",
    "SqliteSignature",
    "columns_schema",
    "file_signature",
    "inspect_table",
    "read_rows",
]

# 列の型 → 列の説明のスキーマの `type`（`json` は型を持たない）
COLUMN_SCHEMA_TYPES = {"text": "string", "integer": "integer", "real": "number"}


@dataclass(frozen=True)
class SqliteSignature:
    """読み直すかを決めるファイルと WAL のファイルの更新日時とサイズ。"""

    db: tuple[int, int]
    wal: tuple[int, int] | None


@dataclass(frozen=True)
class SqliteRows:
    """1 つの行から作った文書と、配信しなかった行の数と警告。"""

    documents: list[Document] = field(default_factory=list[Document])
    omitted: int = 0
    warnings: list[str] = field(default_factory=list[str])
    signature: SqliteSignature | None = None


def _stamp(path: Path) -> tuple[int, int] | None:
    """ファイルの更新日時（ナノ秒）とサイズを返す（無ければ `None`）。"""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def file_signature(path: Path) -> SqliteSignature | None:
    """SQLite のファイルと `-wal` のファイルの更新日時とサイズを返す。"""
    db = _stamp(path)
    if db is None:
        return None
    return SqliteSignature(db=db, wal=_stamp(path.with_name(path.name + "-wal")))


def _quote(identifier: str) -> str:
    """SQL の識別子として引用する。"""
    return '"' + identifier.replace('"', '""') + '"'


def _sqlite_of(table: DocumentTable) -> SqliteTable:
    """`sqlite` を持つ行の `sqlite` を返す。"""
    if table.sqlite is None:
        message = f"SQLite の表を指さない行です: {table.id}"
        raise ValueError(message)
    return table.sqlite


def _id_column(table: DocumentTable) -> str:
    """共通のキー `id` に対応する列の名前。"""
    return table.metadata.get("id", "id")


def _resolve_file(source_root: Path, sqlite: SqliteTable) -> Path | None:
    """`sqlite.file` を配信元のフォルダで解き、配下でなければ `None` を返す。"""
    root = source_root.resolve()
    path = (root / sqlite.file).resolve()
    return path if path.is_relative_to(root) else None


def _connect(path: Path) -> sqlite3.Connection:
    """ファイルを作らず書き込まない接続を開く。"""
    return sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)


def _select(sqlite: SqliteTable, id_column: str) -> tuple[str, str]:
    """行を読む `SELECT` と、`where` に該当する行を数える `SELECT COUNT(*)` を作る。"""
    columns = ", ".join(_quote(column.name) for column in sqlite.columns)
    where = "" if sqlite.where is None else f" WHERE {sqlite.where}"
    order_by = sqlite.order_by or f"{_quote(id_column)} ASC"
    rows = (
        f"SELECT {columns} FROM {_quote(sqlite.table)}{where}"
        f" ORDER BY {order_by} LIMIT {sqlite.limit + 1}"
    )
    count = f"SELECT COUNT(*) FROM {_quote(sqlite.table)}{where}"
    return rows, count


def _decode(
    values: tuple[object, ...], sqlite: SqliteTable, row_id: str, warnings: list[str]
) -> dict[str, Any]:
    """行の値を `columns[]` の並びの辞書にし、`json` の列を配列・オブジェクトにする。"""
    data: dict[str, Any] = {}
    for column, value in zip(sqlite.columns, values, strict=True):
        # json の列: 文字列を JSON として読み、読めない値は空にして警告する
        if column.type == "json" and isinstance(value, str):
            try:
                data[column.name] = json.loads(value)
            except json.JSONDecodeError:
                data[column.name] = None
                warnings.append(f"{row_id}: 列 {column.name} の値を JSON として読めません")
            continue
        data[column.name] = value
    return data


def _document(data: dict[str, Any], index: int, source_id: str, table: DocumentTable) -> Document:
    """行の辞書から 1 件の文書を作る（本文は列の YAML、バージョンは本文のハッシュ）。"""
    sqlite = _sqlite_of(table)
    metadata = resolve_metadata(data, table)
    document_id = str(data[_id_column(table)])
    metadata["id"] = document_id
    if not metadata.get("name"):
        metadata["name"] = document_id
    body = dump_roundtrip(CommentedMap(data))
    return Document(
        id=document_id,
        kind=table.id,
        source_id=source_id,
        path=sqlite.file,
        record_index=index,
        data=data,
        body=body,
        body_path=None,
        metadata=metadata,
        version=content_hash(body),
        created=None,
        updated=None,
    )


def _fetch(
    conn: sqlite3.Connection, sqlite: SqliteTable, id_column: str
) -> tuple[list[tuple[object, ...]], int]:
    """上限までの行と、上限を超えて配信しなかった行の数を読む。"""
    rows_sql, count_sql = _select(sqlite, id_column)
    rows: list[tuple[object, ...]] = conn.execute(rows_sql).fetchall()
    # 上限を超えた: where に該当する行を数えて、配信しない行の数にする
    if len(rows) > sqlite.limit:
        total = int(conn.execute(count_sql).fetchone()[0])
        return rows[: sqlite.limit], total - sqlite.limit
    return rows, 0


def read_rows(source_root: Path, source_id: str, table: DocumentTable) -> SqliteRows:
    """SQLite のファイルを読み取り専用で開き、表かビューの行を 1 行 1 件の文書にする。"""
    sqlite = _sqlite_of(table)
    path = _resolve_file(source_root, sqlite)
    if path is None:
        return SqliteRows(warnings=[f"配信元の外のファイルを指しています: {sqlite.file}"])
    signature = file_signature(path)
    id_column = _id_column(table)
    try:
        conn = _connect(path)
    except sqlite3.Error as error:
        return SqliteRows(warnings=[f"{sqlite.file} を開けません（{error}）"])
    try:
        fetched, omitted = _fetch(conn, sqlite, id_column)
    except sqlite3.Error as error:
        return SqliteRows(warnings=[f"{sqlite.file} の表 {sqlite.table} を読めません（{error}）"])
    finally:
        conn.close()
    names = [column.name for column in sqlite.columns]
    warnings: list[str] = []
    documents: list[Document] = []
    seen: set[str] = set()
    for index, values in enumerate(fetched):
        row_id = str(dict(zip(names, values, strict=True)).get(id_column))
        # 重なる ID: 最初の行だけを残す
        if row_id in seen:
            warnings.append(f"ID が重なる行があります: {row_id}（最初の行だけを配信します）")
            continue
        seen.add(row_id)
        data = _decode(values, sqlite, row_id, warnings)
        documents.append(_document(data, index, source_id, table))
    return SqliteRows(documents=documents, omitted=omitted, warnings=warnings, signature=signature)


def _definition_hash(table: DocumentTable) -> str:
    """行の id・`sqlite`・`metadata`・`alias_type` から行の定義のハッシュを求める。"""
    sqlite = _sqlite_of(table)
    return value_hash(
        {
            "id": table.id,
            "sqlite": sqlite.model_dump(),
            "metadata": table.metadata,
            "alias_type": table.alias_type,
        }
    )


class SqliteRowCache:
    """行の定義ごとに読んだ行を持ち、署名か行の定義が変わったときだけ読み直す。"""

    def __init__(self) -> None:
        # （行の id、行の定義のハッシュ）→ 読んだ結果
        self._entries: dict[tuple[str, str], SqliteRows] = {}
        self._lock = threading.Lock()

    def rows(self, source_root: Path, source_id: str, table: DocumentTable) -> SqliteRows:
        """署名が前回と同じなら読んだ行を、違えば読み直した行を返す。"""
        path = _resolve_file(source_root, _sqlite_of(table))
        signature = None if path is None else file_signature(path)
        key = (table.id, _definition_hash(table))
        with self._lock:
            cached = self._entries.get(key)
            # 前回と同じ署名: 読んだ行を使い回す
            if cached is not None and signature is not None and cached.signature == signature:
                return cached
            result = read_rows(source_root, source_id, table)
            self._entries[key] = result
            return result


def _table_violations(
    conn: sqlite3.Connection, table: DocumentTable, index: int
) -> list[Violation]:
    """表かビューと、`columns[]`・`metadata` が指す列の有無を確かめる。"""
    sqlite = _sqlite_of(table)
    prefix = f"documents[{index}]"
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (sqlite.table,),
    ).fetchone()
    # 表もビューも無い
    if found is None:
        return [
            Violation(
                path=f"{prefix}.sqlite.table",
                rule=f"表かビューがありません: {sqlite.table}",
            )
        ]
    actual = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({_quote(sqlite.table)})")}
    listed = {column.name for column in sqlite.columns}
    violations = [
        Violation(
            path=f"{prefix}.sqlite.columns[{position}].name",
            rule=f"表に列がありません: {column.name}",
        )
        for position, column in enumerate(sqlite.columns)
        if column.name not in actual
    ]
    # metadata が指す列: 表にも columns[] にも要る
    violations.extend(
        Violation(
            path=f"{prefix}.metadata.{key}",
            rule=f"列がありません: {column}",
            fix="表の列を columns[] に記載してください",
        )
        for key, column in table.metadata.items()
        if column not in actual or column not in listed
    )
    return violations


def inspect_table(
    source_root: Path, table: DocumentTable, index: int
) -> tuple[list[Violation], list[Violation]]:
    """`sqlite` を持つ行のファイル・表かビュー・列の有無を確認し、違反と警告を返す。"""
    sqlite = _sqlite_of(table)
    prefix = f"documents[{index}]"
    path = _resolve_file(source_root, sqlite)
    # ファイルが無い・配信元の外を指す
    if path is None or not path.is_file():
        rule = f"ファイルがありません: {sqlite.file}"
        return [Violation(path=f"{prefix}.sqlite.file", rule=rule)], []
    try:
        conn = _connect(path)
        try:
            violations = _table_violations(conn, table, index)
        finally:
            conn.close()
    except sqlite3.Error as error:
        rule = f"ファイルを開けません: {sqlite.file}（{error}）"
        return [Violation(path=f"{prefix}.sqlite.file", rule=rule)], []
    if violations:
        return violations, []
    rows = read_rows(source_root, "", table)
    warnings: list[Violation] = []
    # 上限を超えた行: 配信しない行の数を警告にする
    if rows.omitted:
        warnings.append(
            Violation(
                path=f"{prefix}.sqlite.limit",
                rule=f"limit（{sqlite.limit}）を超えた {rows.omitted} 行を配信していません",
            )
        )
    warnings.extend(Violation(path=f"{prefix}.sqlite", rule=warning) for warning in rows.warnings)
    return [], warnings


def columns_schema(table: DocumentTable) -> dict[str, Any]:
    """`columns[]` から、読み取り API と `describe` が返す JSON Schema を作る。"""
    properties: dict[str, Any] = {}
    for column in _sqlite_of(table).columns:
        node: dict[str, Any] = {"title": column.description}
        schema_type = COLUMN_SCHEMA_TYPES.get(column.type)
        if schema_type is not None:
            node["type"] = schema_type
        properties[column.name] = node
    return {"type": "object", "properties": properties}

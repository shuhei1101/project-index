"""文書のファイルの収集と読み込み。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import posixpath
from datetime import date, datetime, time
from typing import TYPE_CHECKING, Any

from project_index.features.documents.fields import get_field, resolve_metadata
from project_index.features.documents.indexable import is_excluded_file, walk_files
from project_index.features.documents.types import Document, LoadProblem
from project_index.shared.hashing import content_hash, value_hash
from project_index.shared.yaml_io import YamlLoadError, dump_roundtrip, load_yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
    from pathlib import Path

    from project_index.features.history.types import FileDates
    from project_index.features.sources.types import DocumentTable


def collect_files(
    root: Path, table: DocumentTable, *, files: Sequence[str] | None = None
) -> list[str]:
    """文書の行に当たるファイルを配信元の直下から集める。

    `files` は呼び出し元が `walk_files(root)` でたどったパスで、渡されたらフォルダをたどらない。
    """
    candidates = walk_files(root) if files is None else files
    return sorted({path for path in candidates if table.matches(path)})


def _as_datetime(value: Any) -> datetime | None:  # noqa: ANN401
    """ISO 8601 の文字列・日時・日付を日時にする。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        # 日付だけの値は、その日の 0 時（端末のタイムゾーン）にする
        return datetime.combine(value, time.min).astimezone()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _timestamps(data: Mapping[str, Any], key: str, file_dates: FileDates | None) -> datetime | None:
    """git の日時、無ければ内容の項目の日時を返す。"""
    if file_dates is not None:
        return file_dates.created if key == "created" else file_dates.updated
    return _as_datetime(data.get(key))


def _body_file(
    root: Path,
    path: str,
    value: Any,  # noqa: ANN401
    read_body: Callable[[str], str | None] | None = None,
) -> tuple[str, str] | None:
    """`body_file` が指すファイルの `root` からのパスと内容を返す（無い・外を指すなら `None`）。"""
    if not isinstance(value, str) or not value:
        return None
    relative = posixpath.normpath(posixpath.join(posixpath.dirname(path), value))
    if relative == ".." or relative.startswith(("../", "/")):
        return None
    if read_body is not None:
        # 内容は呼び出し元の読み方（commit のファイルなど）で読む
        content = read_body(relative)
        return None if content is None else (relative, content)
    target = root / relative
    try:
        if not target.resolve().is_relative_to(root.resolve()) or not target.is_file():
            return None
        return relative, target.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return None


def _build(
    *,
    data: dict[str, Any],
    body: str,
    body_path: str | None,
    index: int | None,
    version: str,
    path: str,
    table: DocumentTable,
    source_id: str,
    dates: Mapping[str, FileDates],
    fallback_id: str,
) -> Document:
    """内容・本文・バージョンから 1 件の文書を作る。"""
    key_path = body_path or path
    metadata = resolve_metadata(data, table)
    document_id = str(metadata["id"]) if metadata.get("id") is not None else fallback_id
    if not metadata.get("name"):
        # `records` の要素で `body_file` が無ければ、指すファイルが無いので ID にする
        metadata["name"] = (
            document_id
            if index is not None and body_path is None
            else posixpath.splitext(posixpath.basename(key_path))[0]
        )
    file_dates = dates.get(key_path)
    return Document(
        id=document_id,
        kind=table.id,
        source_id=source_id,
        path=path,
        record_index=index,
        data=data,
        body=body,
        body_path=body_path,
        metadata=metadata,
        version=version,
        created=_timestamps(data, "created", file_dates),
        updated=_timestamps(data, "updated", file_dates),
    )


def documents_from_text(
    text: str,
    root: Path,
    path: str,
    table: DocumentTable,
    *,
    source_id: str,
    dates: Mapping[str, FileDates] | None = None,
    read_body: Callable[[str], str | None] | None = None,
) -> tuple[list[Document], list[LoadProblem]]:
    """1 つのファイルの内容の文字列を、文書の行に従って 1 件以上の文書にする。"""
    dates = dates or {}
    common: dict[str, Any] = {"path": path, "table": table, "source_id": source_id, "dates": dates}
    try:
        loaded = load_yaml(text, file=path)
    except YamlLoadError as error:
        return [], [
            LoadProblem(
                path=path,
                reason="unreadable",
                detail=str(error),
                line=error.line,
                column=error.column,
            )
        ]
    if table.records is None:
        if not isinstance(loaded, dict):
            return [], [
                LoadProblem(path=path, reason="not_mapping", detail="最上位が辞書ではありません")
            ]
        return [
            _build(
                data=loaded,
                body=text,
                body_path=None,
                index=None,
                version=content_hash(text),
                fallback_id=path,
                **common,
            )
        ], []
    if not isinstance(loaded, dict):
        return [], [
            LoadProblem(path=path, reason="not_mapping", detail="最上位が辞書ではありません")
        ]
    records = get_field(loaded, table.records)
    documents: list[Document] = []
    problems: list[LoadProblem] = []
    for index, record in enumerate(records if isinstance(records, list) else []):
        if not isinstance(record, dict):
            problems.append(
                LoadProblem(
                    path=path,
                    reason="not_mapping",
                    detail=f"{table.records}[{index}] が辞書ではありません",
                )
            )
            continue
        body_path: str | None = None
        if table.body_file is not None:
            value = get_field(record, table.body_file)
            found = _body_file(root, path, value, read_body)
            if found is None:
                problems.append(
                    LoadProblem(
                        path=path,
                        reason="missing_body_file",
                        detail=f"{table.records}[{index}] の {table.body_file}（{value}）が指すファイルがありません",
                    )
                )
                continue
            body_path, body = found
            fallback_id = body_path
        else:
            body = dump_roundtrip(record)  # type: ignore[arg-type]
            fallback_id = f"{path}#{index}"
        documents.append(
            _build(
                data=record,
                body=body,
                body_path=body_path,
                index=index,
                version=value_hash(record),
                fallback_id=fallback_id,
                **common,
            )
        )
    return documents, problems


def load_file(
    root: Path,
    path: str,
    table: DocumentTable,
    *,
    source_id: str,
    dates: Mapping[str, FileDates] | None = None,
) -> tuple[list[Document], list[LoadProblem]]:
    """1 つのファイルを読み、文書の行に従って 1 件以上の文書にする。"""
    try:
        text = (root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return [], [LoadProblem(path=path, reason="unreadable", detail=str(error))]
    return documents_from_text(text, root, path, table, source_id=source_id, dates=dates)


def unindexed_files(
    root: Path,
    index_path: str,
    body_paths: Collection[str],
    table: DocumentTable,
    *,
    files: Sequence[str] | None = None,
) -> list[str]:
    """管理用の YAML のフォルダの配下で、どの行も指していないファイルを `root` からのパスで返す。

    行の `exclude` に当たるファイルと、除外の条件に当たるファイルは数えない。
    `files` は呼び出し元が `walk_files(root)` でたどったパスで、渡されたらフォルダをたどらない。
    """
    start = posixpath.dirname(index_path) or "."
    candidates: Iterable[str]
    if files is None:
        candidates = walk_files(root, start=start)
    elif start == ".":
        # 管理用の YAML が配信元の直下にある: たどった全てのパスが配下
        candidates = files
    else:
        # たどったパスのうち、管理用の YAML のフォルダの配下だけを見る
        prefix = f"{start}/"
        candidates = [path for path in files if path.startswith(prefix)]
    excluded = {index_path, *body_paths}
    return sorted(
        path
        for path in candidates
        if path not in excluded and not table.excludes(path) and not is_excluded_file(root, path)
    )

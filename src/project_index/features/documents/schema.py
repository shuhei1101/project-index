"""種類のスキーマの `$ref` の解決。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownMemberType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import logging
import posixpath
from collections.abc import Callable, Mapping
from pathlib import Path, PurePath, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urldefrag

from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from project_index.features.sources.types import DocumentTable, ServedSource

type ReadText = Callable[[str], str | None]

logger = logging.getLogger(__name__)


class _Unresolved(Exception):  # noqa: N818
    """`$ref` の参照先が無い・読めないことを表す。"""


def _disk_schema(path: PurePath, cache: dict[str, Any]) -> Any:  # noqa: ANN401
    """参照先のスキーマのファイルをディスクから読む（同じファイルは 1 回だけ読む）。"""
    key = str(path)
    if key not in cache:
        try:
            cache[key] = load_yaml(Path(path).read_text(encoding="utf-8"), file=key)
        except (OSError, UnicodeDecodeError, YamlLoadError) as error:
            raise _Unresolved(str(error)) from error
    return cache[key]


def _read_schema(path: PurePath, read: ReadText, cache: dict[str, Any]) -> Any:  # noqa: ANN401
    """参照先のスキーマのファイルを `read` で読む（同じファイルは 1 回だけ読む）。"""
    key = path.as_posix()
    # リポジトリの直下より上を指す参照先は無いものとして扱う
    if key == ".." or key.startswith(("../", "/")):
        msg = f"{key} はリポジトリの外です"
        raise _Unresolved(msg)
    if key not in cache:
        text = read(key)
        if text is None:
            msg = f"{key} がありません"
            raise _Unresolved(msg)
        try:
            cache[key] = load_yaml(text, file=key)
        except YamlLoadError as error:
            raise _Unresolved(str(error)) from error
    return cache[key]


def _pointer(document: Any, fragment: str) -> Any:  # noqa: ANN401
    """JSON Pointer（`/$defs/x`）でたどる。"""
    current = document
    for raw in [part for part in fragment.split("/") if part]:
        key = unquote(raw).replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(key)]
            except (ValueError, IndexError) as error:
                msg = f"{fragment} がありません"
                raise _Unresolved(msg) from error
        elif isinstance(current, Mapping) and key in current:
            current = current[key]
        else:
            msg = f"{fragment} がありません"
            raise _Unresolved(msg)
    return current


def _target(current: PurePath, location: str, *, posix: bool) -> PurePath:
    """`$ref` の参照先のファイルのパスを、今のファイルのフォルダから組み立てる。"""
    if not location:
        return current
    joined = current.parent / unquote(location)
    # 読み取りの関数で読むときは、`..` を畳んだリポジトリの直下からのパスにする
    return PurePosixPath(posixpath.normpath(joined.as_posix())) if posix else joined


def resolve_schema_refs(
    schema: Mapping[str, Any], base: Path | PurePosixPath, *, read: ReadText | None = None
) -> dict[str, Any]:
    """種類のスキーマの `$ref` を参照先の中身で置き換えたスキーマを返す。"""
    files: dict[str, Any] = {}

    def load(path: PurePath) -> Any:  # noqa: ANN401
        if read is None:
            return _disk_schema(Path(path).resolve(), files)
        return _read_schema(path, read, files)

    def resolve(value: Any, current: PurePath, document: Any, stack: tuple[str, ...]) -> Any:  # noqa: ANN401
        if isinstance(value, list):
            return [resolve(item, current, document, stack) for item in value]
        if not isinstance(value, Mapping):
            return value
        ref = value.get("$ref")
        if not isinstance(ref, str):
            # 最上位の `$defs` は参照先として使うので、そのまま残す
            return {
                key: item
                if key == "$defs" and not stack
                else resolve(item, current, document, stack)
                for key, item in value.items()
            }
        location, fragment = urldefrag(ref)
        target_path = _target(current, location, posix=read is not None)
        identity = f"{target_path}#{fragment}"
        if identity in stack:
            logger.warning("スキーマの循環する参照を解かずに残した（%s・%s）", current, ref)
            return dict(value)
        try:
            target_doc = document if not location else load(target_path)
            target = _pointer(target_doc, fragment)
        except _Unresolved as error:
            logger.warning("スキーマの参照を解けなかった（%s・%s・%s）", current, ref, error)
            return dict(value)
        resolved = resolve(target, target_path, target_doc, (*stack, identity))
        if not isinstance(resolved, dict):
            return resolved
        extra = {
            key: resolve(item, current, document, stack)
            for key, item in value.items()
            if key != "$ref"
        }
        return {**resolved, **extra}

    result = resolve(schema, base, schema, ())
    return result  # type: ignore[no-any-return]


def startup_schema(source: ServedSource, table: DocumentTable) -> dict[str, Any]:
    """配信元が起動時に読んだ行のスキーマを、`$ref` を解いて返す。"""
    startup = source.schemas.get(table.id, {})
    # ほかの配信元の参照は、起動時に参照先のリビジョンで `$ref` まで解いてある
    if not isinstance(table.schema_path, str):
        return dict(startup)
    return resolve_schema_refs(startup, source.root / table.schema_path)


def records_item_schema(schema: Mapping[str, Any], records: str) -> dict[str, Any] | None:
    """ファイル全体のスキーマから `records` の要素 1 つのスキーマ（`properties.{records}.items`）を取り出す。"""
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return None
    array = properties.get(records)
    if not isinstance(array, Mapping):
        return None
    items = array.get("items")
    if not isinstance(items, Mapping):
        return None
    return dict(items)

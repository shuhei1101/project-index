"""種類のスキーマの `$ref` の解決。"""

from __future__ import annotations

import logging
import posixpath
from collections.abc import Callable, Mapping
from pathlib import Path, PurePath, PurePosixPath
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import unquote, urldefrag

from project_index.shared.narrowing import is_dict, is_list
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from project_index.features.sources.types import DocumentTable, ServedSource

type ReadText = Callable[[str], str | None]

logger = logging.getLogger(__name__)


class _UnresolvedRefError(Exception):
    """`$ref` の参照先が無い・読めないことを表す。"""


def _disk_schema(path: PurePath, cache: dict[str, object]) -> object:
    """参照先のスキーマのファイルをディスクから読む（同じファイルは 1 回だけ読む）。"""
    key = str(path)
    if key not in cache:
        try:
            cache[key] = load_yaml(Path(path).read_text(encoding="utf-8"), file=key)
        except (OSError, UnicodeDecodeError, YamlLoadError) as error:
            raise _UnresolvedRefError(str(error)) from error
    return cache[key]


def _read_schema(path: PurePath, read: ReadText, cache: dict[str, object]) -> object:
    """参照先のスキーマのファイルを `read` で読む（同じファイルは 1 回だけ読む）。"""
    key = path.as_posix()
    # リポジトリの直下より上を指す参照先は無いものとして扱う
    if key == ".." or key.startswith(("../", "/")):
        msg = f"{key} はリポジトリの外です"
        raise _UnresolvedRefError(msg)
    if key not in cache:
        text = read(key)
        if text is None:
            msg = f"{key} がありません"
            raise _UnresolvedRefError(msg)
        try:
            cache[key] = load_yaml(text, file=key)
        except YamlLoadError as error:
            raise _UnresolvedRefError(str(error)) from error
    return cache[key]


def _pointer(document: object, fragment: str) -> object:
    """JSON Pointer（`/$defs/x`）でたどる。"""
    current = document
    for raw in [part for part in fragment.split("/") if part]:
        key = unquote(raw).replace("~1", "/").replace("~0", "~")
        if is_list(current):
            try:
                current = current[int(key)]
            except (ValueError, IndexError) as error:
                msg = f"{fragment} がありません"
                raise _UnresolvedRefError(msg) from error
        elif is_dict(current) and key in current:
            current = current[key]
        else:
            msg = f"{fragment} がありません"
            raise _UnresolvedRefError(msg)
    return current


def _target(current: PurePath, location: str, *, posix: bool) -> PurePath:
    """`$ref` の参照先のファイルのパスを、今のファイルのフォルダから組み立てる。"""
    if not location:
        return current
    joined = current.parent / unquote(location)
    # 読み取りの関数で読むときは、`..` を畳んだリポジトリの直下からのパスにする
    return PurePosixPath(posixpath.normpath(joined.as_posix())) if posix else joined


class _Resolver:
    """スキーマの `$ref` を参照先の中身で置き換える（参照先のファイルは 1 回だけ読む）。"""

    def __init__(self, read: ReadText | None) -> None:
        self._read = read
        self._files: dict[str, object] = {}

    def _load(self, path: PurePath) -> object:
        """参照先のファイルを読む（`read` が無ければディスクから）。"""
        if self._read is None:
            return _disk_schema(Path(path).resolve(), self._files)
        return _read_schema(path, self._read, self._files)

    def resolve(
        self, value: object, current: PurePath, document: object, stack: tuple[str, ...]
    ) -> object:
        """値の中の `$ref` を再帰的に解く。"""
        if is_list(value):
            return [self.resolve(item, current, document, stack) for item in value]
        if not is_dict(value):
            return value
        ref = value.get("$ref")
        if isinstance(ref, str):
            return self._resolve_ref(value, ref, current, document, stack)
        return {
            key: self._resolve_defs(item, current, document)
            if key == "$defs" and not stack
            else self.resolve(item, current, document, stack)
            for key, item in value.items()
        }

    def _resolve_defs(self, defs: object, current: PurePath, document: object) -> object:
        """最上位の `$defs` を参照先として残したまま、各定義の中の `$ref` を解く。"""
        if not is_dict(defs):
            return defs
        # 定義を自分自身への参照をたどる途中として解き、自分へ戻る `#/$defs/{名前}` だけを残す
        return {
            name: self.resolve(item, current, document, (f"{current}#/$defs/{name}",))
            for name, item in defs.items()
        }

    def _resolve_ref(
        self,
        value: dict[object, object],
        ref: str,
        current: PurePath,
        document: object,
        stack: tuple[str, ...],
    ) -> object:
        """`$ref` を持つ辞書を、参照先の中身と `$ref` 以外のキーを合わせた値にする。"""
        location, fragment = urldefrag(ref)
        target_path = _target(current, location, posix=self._read is not None)
        identity = f"{target_path}#{fragment}"
        if identity in stack:
            logger.warning("スキーマの循環する参照を解かずに残した（%s・%s）", current, ref)
            return dict(value)
        try:
            target_doc = document if not location else self._load(target_path)
            target = _pointer(target_doc, fragment)
        except _UnresolvedRefError as error:
            logger.warning("スキーマの参照を解けなかった（%s・%s・%s）", current, ref, error)
            return dict(value)
        resolved = self.resolve(target, target_path, target_doc, (*stack, identity))
        if not is_dict(resolved):
            return resolved
        extra = {
            key: self.resolve(item, current, document, stack)
            for key, item in value.items()
            if key != "$ref"
        }
        return {**resolved, **extra}


def resolve_schema_refs(
    schema: Mapping[str, Any], base: Path | PurePosixPath, *, read: ReadText | None = None
) -> dict[str, Any]:
    """種類のスキーマの `$ref` を参照先の中身で置き換えたスキーマを返す。"""
    result = _Resolver(read).resolve(schema, base, schema, ())
    # 最上位の `$ref` が辞書でない値を指したときは、解かずに返す
    if not is_dict(result):
        return dict(schema)
    return cast("dict[str, Any]", result)


def startup_schema(source: ServedSource, table: DocumentTable) -> dict[str, Any]:
    """配信元が起動時に読んだ行のスキーマを、`$ref` を解いて返す。"""
    startup = source.schemas.get(table.id, {})
    # ほかの配信元の参照は、起動時に参照先のリビジョンで `$ref` まで解いてある
    if not isinstance(table.schema_path, str):
        return dict(startup)
    return resolve_schema_refs(startup, source.root / table.schema_path)


def records_item_schema(schema: Mapping[str, Any], records: str) -> dict[str, Any] | None:
    """ファイル全体のスキーマから `records` の要素 1 つのスキーマ（`properties.{records}.items`）を取り出す。"""
    properties: object = schema.get("properties")
    array = properties.get(records) if is_dict(properties) else None
    items = array.get("items") if is_dict(array) else None
    if not is_dict(items):
        return None
    return cast("dict[str, Any]", items)

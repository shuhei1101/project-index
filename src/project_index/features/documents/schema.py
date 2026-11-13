"""種類のスキーマの `$ref` の解決。"""

from __future__ import annotations

import logging
import os.path
import posixpath
from collections.abc import Callable, Mapping
from pathlib import Path, PurePath, PurePosixPath
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote, unquote, urldefrag

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


def _relative_name(base: PurePath, target: PurePath, fragment: str, *, posix: bool) -> str:
    """参照先の定義を、`base` のフォルダからの相対パスと JSON Pointer の名前にする。"""
    if posix:
        relative = posixpath.relpath(target.as_posix(), base.parent.as_posix())
    else:
        relative = PurePath(os.path.relpath(target, base.parent)).as_posix()
    return f"{relative}#{fragment}"


def _defs_ref(name: str) -> str:
    """最上位の `$defs` の名前を指す `$ref` を作る（JSON Pointer の区切りとしてエスケープし、URL エンコードする）。"""
    return "#/$defs/" + quote(name.replace("~", "~0").replace("/", "~1"), safe="")


class _Resolver:
    """スキーマの `$ref` を参照先の中身で置き換える（参照先のファイルは 1 回だけ読む）。"""

    def __init__(self, read: ReadText | None, base: PurePath, names: set[str]) -> None:
        self._read = read
        self._base = base
        self._files: dict[str, object] = {}
        # 最上位の `$defs` の定義・加える定義を解いている途中か（途中の循環は警告しない）
        self._in_defs = False
        # 最上位の `$defs` で使っている名前（種類のスキーマの定義と加えた定義）
        self._names = set(names)
        # 別のファイルの中で循環する参照先（`{ファイル}#{JSON Pointer}`）ごとの加えた名前
        self._hoisted: dict[str, str] = {}
        # 最上位の `$defs` へ加える定義
        self.hoisted_defs: dict[str, object] = {}

    def _is_base(self, path: PurePath) -> bool:
        """参照先のファイルが種類のスキーマのファイルか。"""
        return os.path.normpath(path) == os.path.normpath(self._base)

    def _unique_name(self, name: str) -> str:
        """最上位の `$defs` の名前と重ならなくなるまで末尾に連番を付ける。"""
        candidate = name
        number = 2
        while candidate in self._names:
            candidate = f"{name}-{number}"
            number += 1
        self._names.add(candidate)
        return candidate

    def _hoist(
        self, identity: str, target_path: PurePath, fragment: str, target_doc: object
    ) -> str:
        """別のファイルの中で循環する参照先の定義を最上位の `$defs` へ加え、その名前を返す。"""
        if identity in self._hoisted:
            return self._hoisted[identity]
        name = self._unique_name(
            _relative_name(self._base, target_path, fragment, posix=self._read is not None)
        )
        # 定義を解く途中で同じ参照先に戻ったときに同じ名前を指すよう、解く前に登録する
        self._hoisted[identity] = name
        in_defs = self._in_defs
        self._in_defs = True
        try:
            self.hoisted_defs[name] = self.resolve(
                _pointer(target_doc, fragment), target_path, target_doc, (identity,)
            )
        finally:
            self._in_defs = in_defs
        return name

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
        self._in_defs = True
        try:
            return {
                name: self.resolve(item, current, document, (f"{current}#/$defs/{name}",))
                for name, item in defs.items()
            }
        finally:
            self._in_defs = False

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
            # 循環する参照は解かずに残す（`$defs` の定義の中の循環は、定義の外からたどった側で警告する）
            if not self._in_defs:
                logger.warning("スキーマの循環する参照を解かずに残した（%s・%s）", current, ref)
            # 種類のスキーマの中の循環: 最上位の `$defs` を指したまま残す
            if self._is_base(target_path):
                # 別のファイルから種類のスキーマへ戻る参照は、ファイルのパスを除いて種類のスキーマを指す
                return {**value, "$ref": f"#{fragment}"} if location else dict(value)
            # 別のファイルの中の循環: 参照先の定義を最上位の `$defs` へ加えた名前を指す
            target_doc = document if not location else self._load(target_path)
            name = self._hoist(identity, target_path, fragment, target_doc)
            return {**value, "$ref": _defs_ref(name)}
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
    defs: object = schema.get("$defs")
    names = {name for name in defs if isinstance(name, str)} if is_dict(defs) else set[str]()
    resolver = _Resolver(read, base, names)
    result = resolver.resolve(schema, base, schema, ())
    # 最上位の `$ref` が辞書でない値を指したときは、解かずに返す
    if not is_dict(result):
        return dict(schema)
    # 別のファイルの中で循環する定義があれば、最上位の `$defs` へ加える
    if resolver.hoisted_defs:
        resolved_defs = result.get("$defs")
        result = {
            **result,
            "$defs": {**(resolved_defs if is_dict(resolved_defs) else {}), **resolver.hoisted_defs},
        }
    return cast("dict[str, Any]", result)


def startup_schema(source: ServedSource, table: DocumentTable) -> dict[str, Any]:
    """配信元が起動時に読んだ行のスキーマを、`$ref` を解いて返す。"""
    startup = source.schemas.get(table.id, {})
    # ほかの配信元の参照は、起動時に参照先のリビジョンで `$ref` まで解いてある
    if not isinstance(table.schema_path, str):
        return dict(startup)
    return resolve_schema_refs(startup, source.config_root / table.schema_path)


def records_item_schema(schema: Mapping[str, Any], records: str) -> dict[str, Any] | None:
    """ファイル全体のスキーマから `records` の要素 1 つのスキーマ（`properties.{records}.items`）を取り出す。"""
    properties: object = schema.get("properties")
    array = properties.get(records) if is_dict(properties) else None
    items = array.get("items") if is_dict(array) else None
    if not is_dict(items):
        return None
    return cast("dict[str, Any]", items)

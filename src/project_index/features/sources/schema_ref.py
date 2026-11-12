"""`documents[].schema` でほかの配信元のリビジョンのスキーマを指す参照と、その読み取り。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel, ConfigDict

from project_index.features.documents.schema import resolve_schema_refs
from project_index.features.history.query import read_file_at, resolve_ref
from project_index.integrations.git import repo_root
from project_index.shared.errors import RefNotFoundError
from project_index.shared.narrowing import is_dict
from project_index.shared.yaml_io import YamlLoadError, load_yaml

if TYPE_CHECKING:
    from project_index.features.settings.types import TerminalConfig

type SchemaRefLookup = Callable[[str], Path | None]


class SchemaRef(BaseModel):
    """`documents[].schema` のオブジェクトの書き方（ほかの配信元のスキーマの参照）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # 端末の設定の `sources[]` の行の ID（`id` が無い行は、その行の先頭の設定の `name`）
    source: str
    # 参照先のリポジトリの直下からのスキーマのパス
    path: str
    # タグか commit
    ref: str


@dataclass(frozen=True)
class RefSchema:
    """参照を解いて読んだスキーマと、読んだ commit。"""

    schema: dict[str, Any]
    commit: str


class SchemaRefError(Exception):
    """参照先の配信元・リビジョン・パスのどれかが見つからない。"""

    def __init__(self, rule: str) -> None:
        super().__init__(rule)
        self.rule = rule


def _config_name(config: Path) -> str | None:
    """設定のファイルの `name` を読む（読めなければ `None`）。"""
    try:
        value = load_yaml(config.read_text(encoding="utf-8"), file=str(config))
    except OSError, UnicodeDecodeError, YamlLoadError:
        return None
    name = value.get("name") if is_dict(value) else None
    return name if isinstance(name, str) else None


def terminal_lookup(terminal: TerminalConfig) -> SchemaRefLookup:
    """端末の設定の `sources[]` から、配信元の ID → 先頭の設定のファイルの引き当てを作る。"""
    table: dict[str, Path] = {}
    # `enabled` によらず全ての行を載せ、配信していない参照先も読めるようにする
    for entry in terminal.sources:
        config = Path(entry.config[0]).expanduser()
        source_id = entry.id or _config_name(config)
        # `id` も読める `name` も無い行は引けない
        if source_id is None:
            continue
        table.setdefault(source_id, config)
    return table.get


def read_schema_ref(ref: SchemaRef, *, lookup: SchemaRefLookup) -> RefSchema:
    """参照先のリポジトリから `ref` を commit に解いたリビジョンのスキーマを読み、同じ commit の中で `$ref` を解く。"""
    config = lookup(ref.source)
    if config is None:
        msg = f"配信元 {ref.source} が端末の設定にありません"
        raise SchemaRefError(msg)
    top = repo_root(config.parent)
    if top is None:
        msg = f"配信元 {ref.source} は Git のリポジトリではありません"
        raise SchemaRefError(msg)
    try:
        commit = resolve_ref(top, ref.ref, date_base=ref.ref).commit
    except RefNotFoundError as error:
        msg = f"配信元 {ref.source} に {ref.ref} がありません"
        raise SchemaRefError(msg) from error
    text = read_file_at(top, commit, ref.path)
    if text is None:
        msg = f"{ref.ref} に {ref.path} がありません"
        raise SchemaRefError(msg)
    try:
        raw = load_yaml(text, file=ref.path)
    except YamlLoadError as error:
        msg = f"{ref.path} を読み込めません"
        raise SchemaRefError(msg) from error
    if not is_dict(raw):
        msg = f"{ref.path} を読み込めません"
        raise SchemaRefError(msg)
    # 同じ commit のファイルを読み、読めなかったパスを控える
    missing: list[str] = []

    def read(path: str) -> str | None:
        found = read_file_at(top, commit, path)
        if found is None:
            missing.append(path)
        return found

    # YAML から読んだ辞書のキーは文字列として扱う
    schema = resolve_schema_refs(cast("dict[str, Any]", raw), PurePosixPath(ref.path), read=read)
    # `$ref` の参照先がそのリビジョンに無ければ誤りにする
    if missing:
        msg = f"{ref.ref} に {missing[0]} がありません"
        raise SchemaRefError(msg)
    return RefSchema(schema=schema, commit=commit)

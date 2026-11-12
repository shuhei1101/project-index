"""エイリアスのキーの検証と、照合する語の一覧。"""

from __future__ import annotations

import functools
import unicodedata
from importlib import resources
from typing import TYPE_CHECKING, Any, cast

from project_index.features.documents.types import (
    AliasCollection,
    AliasEntry,
    Document,
    MatchWord,
)
from project_index.shared.errors import Violation
from project_index.shared.narrowing import is_dict, is_list
from project_index.shared.yaml_io import load_yaml

if TYPE_CHECKING:
    from collections.abc import Sequence

    from project_index.features.sources.types import ServedSource

ALIAS_SCHEMA_PATH = "schemas/aliases.schema.yaml"
ALIAS_SOURCE_PATH = "schemas/aliases.source.yaml"
ALIAS_REQUIRED_KEYS: dict[str, tuple[str | tuple[str, ...], ...]] = {
    "term": ("id", "name", "description"),
    "doc": ("id", "name", "description"),
    "command": ("id", "name", "command"),
    "url": ("id", "name", "url"),
    "skill": ("id", "name", "skill"),
    "tool": ("id", "name", "tool"),
    "path": ("id", "name", "path"),
    "env": ("id", "name", ("url", "port")),
    "avoid": ("id", "name", "replacement"),
}
ALIAS_LIST_KEYS = ("aliases", "avoid")
ENTRY_KEYS = ("id", "name", "aliases", "description", "avoid")


def _read(path: str) -> dict[str, Any]:
    """配布に同梱した、最上位が辞書の YAML のファイルを読む。"""
    value = load_yaml(resources.files("project_index").joinpath(path).read_text(encoding="utf-8"))
    if not is_dict(value):
        msg = f"{path} の最上位が辞書ではありません"
        raise TypeError(msg)
    # YAML から読んだ辞書のキーは文字列として扱う
    return cast("dict[str, Any]", value)


@functools.cache
def alias_schema() -> dict[str, Any]:
    """同梱した alias-inject のエイリアスのスキーマを返す。"""
    return _read(ALIAS_SCHEMA_PATH)


def alias_schema_version() -> str:
    """エイリアスのスキーマの取り込み元のタグを返す。"""
    return str(_read(ALIAS_SOURCE_PATH)["tag"])


def _alias_keys() -> list[str]:
    """スキーマの `metadata` のキー（エイリアスのキー）。"""
    return list(alias_schema()["$defs"]["alias"]["properties"]["metadata"]["properties"])


def _empty(value: object) -> bool:
    """値が無いか空文字か。"""
    return value is None or value == ""


def _type_rule(key: str, value: object) -> str | None:
    """エイリアスのキーの値の型の誤りを返す。"""
    if key in ALIAS_LIST_KEYS:
        if isinstance(value, str):
            return None
        if is_list(value) and value and all(isinstance(item, str) for item in value):
            return None
        return "文字列か文字列の並びではありません"
    if key == "related":
        if is_list(value) and all(_is_related_item(item) for item in value):
            return None
        return "related の要素は文書の ID か to を持つ辞書です"
    if key == "port":
        valid = isinstance(value, (int, str)) and not isinstance(value, bool)
        return None if valid else "整数か文字列ではありません"
    return None if isinstance(value, str) else "文字列ではありません"


def _is_related_item(item: object) -> bool:
    """`related` の要素が文書の ID か、`to` を持つ辞書か。"""
    return isinstance(item, str) or (is_dict(item) and isinstance(item.get("to"), str))


def check_alias_document(document: Document) -> list[Violation]:
    """文書 1 件のエイリアスのキーの値を、スキーマのキーと引用の種類の必須で検証する。"""
    metadata = document.metadata
    violations: list[Violation] = []
    for required in ALIAS_REQUIRED_KEYS.get(str(metadata.get("alias_type")), ()):
        if isinstance(required, tuple):
            if all(_empty(metadata.get(key)) for key in required):
                violations.append(
                    Violation(
                        path=required[0],
                        rule=f"{'・'.join(required)} のどれか 1 つが要ります",
                        doc=document.path,
                    )
                )
        elif _empty(metadata.get(required)):
            violations.append(Violation(path=required, rule="必須のキーが無い", doc=document.path))
    for key in _alias_keys():
        value = metadata.get(key)
        if value is None:
            continue
        rule = _type_rule(key, value)
        if rule is not None:
            violations.append(Violation(path=key, rule=rule, doc=document.path))
    return violations


def _as_list(value: object) -> list[str]:
    """文字列 1 つを要素 1 つの並びにする（検証を通った文字列の並びはそのまま）。"""
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str)] if is_list(value) else []


def collect_aliases(source: ServedSource, documents: Sequence[Document]) -> AliasCollection:
    """`alias_type` を持つ行の文書を検証し、通った文書のエイリアスと違反を返す。"""
    has_alias_rows = any(
        row.enabled and row.alias_type is not None for row in source.config.documents
    )
    entries: list[AliasEntry] = []
    violations: list[Violation] = []
    keys = _alias_keys()
    for document in documents:
        metadata = document.metadata
        if "alias_type" not in metadata:
            continue
        found = check_alias_document(document)
        if found:
            violations.extend(found)
            continue
        avoid = metadata.get("avoid")
        entries.append(
            AliasEntry(
                id=document.id,
                name=str(metadata["name"]),
                aliases=_as_list(metadata.get("aliases", [])),
                description=metadata.get("description"),
                alias_type=metadata["alias_type"],
                avoid=None if avoid is None else _as_list(avoid),
                extra={
                    key: metadata[key]
                    for key in keys
                    if key not in ENTRY_KEYS and metadata.get(key) is not None
                },
            )
        )
    return AliasCollection(entries=entries, violations=violations, has_alias_rows=has_alias_rows)


def match_words(entries: Sequence[AliasEntry]) -> list[MatchWord]:
    """エイリアスから、照合する語を指す文書の ID とともに並べる。"""
    words: list[MatchWord] = []
    for entry in entries:
        words.append(MatchWord(word=entry.name, id=entry.id, kind="name"))
        words.extend(MatchWord(word=alias, id=entry.id, kind="alias") for alias in entry.aliases)
    return words


def _normalize(text: str) -> str:
    """条件の比較と同じ正規化（NFKC と `casefold`）。"""
    return unicodedata.normalize("NFKC", text).casefold()


def term_ids(entries: Sequence[AliasEntry], term: str) -> set[str]:
    """`name` か `aliases` が用語に一致するエイリアスの文書の ID を返す。"""
    target = _normalize(term)
    return {word.id for word in match_words(entries) if _normalize(word.word) == target}

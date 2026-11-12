"""文書と読み込みの結果の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from project_index.shared.errors import Violation

AliasType = Literal["term", "doc", "command", "url", "skill", "tool", "path", "env", "avoid"]


@dataclass(frozen=True)
class Document:
    """ファイル 1 つか `records` の要素 1 つから作った 1 件の文書。"""

    id: str
    kind: str
    source_id: str
    path: str
    record_index: int | None
    data: dict[str, Any]
    body: str
    body_path: str | None
    metadata: dict[str, Any]
    version: str
    created: datetime | None
    updated: datetime | None


@dataclass(frozen=True)
class LoadProblem:
    """文書にできなかったファイルと理由。"""

    path: str
    reason: Literal["unreadable", "duplicate_id", "missing_body_file", "not_mapping"]
    detail: str
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class SyncReport:
    """1 つの配信元の `metadata` の列の欠けと、管理用の YAML とファイルのずれ。"""

    source_id: str
    missing_refs: list[str] = field(default_factory=list[str])
    unindexed_files: list[str] = field(default_factory=list[str])
    missing_body_files: list[str] = field(default_factory=list[str])
    # source を持たない related[].to が配信元のどの文書の ID にも当たらないもの（`{行の id}: {文書の id}: {to}`）
    unresolved_related: list[str] = field(default_factory=list[str])
    alias_violations: list[Violation] = field(default_factory=list[Violation])


@dataclass(frozen=True)
class LoadResult:
    """読めた文書と読めなかったファイル。"""

    documents: list[Document] = field(default_factory=list[Document])
    problems: list[LoadProblem] = field(default_factory=list[LoadProblem])


@dataclass(frozen=True, slots=True, kw_only=True)
class AliasEntry:
    """`alias_type` を持つ行の文書 1 件のエイリアスのキーの値。"""

    id: str
    name: str
    aliases: list[str] = field(default_factory=list[str])
    description: str | None = None
    alias_type: AliasType
    avoid: list[str] | None = None
    extra: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True, kw_only=True)
class MatchWord:
    """照合する語と、語が指す文書の ID。"""

    word: str
    id: str
    kind: Literal["name", "alias"]


@dataclass(frozen=True, slots=True, kw_only=True)
class AliasCollection:
    """検証に通ったエイリアスと違反。"""

    entries: list[AliasEntry] = field(default_factory=list[AliasEntry])
    violations: list[Violation] = field(default_factory=list[Violation])
    has_alias_rows: bool = False

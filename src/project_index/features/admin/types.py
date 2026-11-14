"""管理の MCP の `status`・`reload`・`check_project`・`try_convert`・`write_nav` の要求と結果の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from project_index.features.read.types import NavAutoCount
from project_index.features.sources.types import ServedSource, SourceStatusKind
from project_index.shared.errors import Violation

if TYPE_CHECKING:
    from typing import Self

    from project_index.features.documents.types import SyncReport

# `check_project` が返す同期のずれの内訳の件数
SYNC_ITEMS_LIMIT = 50

# 設定の `version` と project-index が参照できるバージョンの比較
type VersionState = Literal["current", "old", "newer"]


@dataclass(frozen=True)
class SyncCounts:
    """文書のストアの『メタデータのずれ』の 4 つの並びの件数。"""

    missing_refs: int
    unindexed_files: int
    missing_body_files: int
    unresolved_related: int

    @classmethod
    def of(cls, report: SyncReport) -> Self:
        """`SyncReport` から作る。"""
        return cls(
            missing_refs=len(report.missing_refs),
            unindexed_files=len(report.unindexed_files),
            missing_body_files=len(report.missing_body_files),
            unresolved_related=len(report.unresolved_related),
        )


@dataclass(frozen=True)
class SyncItem:
    """同期のずれ 1 件の種類と値。"""

    kind: Literal["missing_refs", "unindexed_files", "missing_body_files", "unresolved_related"]
    path: str


@dataclass(frozen=True)
class SourceState:
    """`status` と `reload` が返す配信元 1 つの状態。"""

    id: str
    status: SourceStatusKind
    errors: list[str]
    config_version: str | None
    version_state: VersionState | None
    sync: SyncCounts | None


@dataclass(frozen=True)
class TerminalState:
    """読んだ端末の設定のパスとバージョンの新旧。"""

    file: str
    version_state: VersionState


@dataclass(frozen=True)
class ServerStatus:
    """`status` の結果。"""

    address: str
    version: str
    pid: int
    terminal: TerminalState
    sources: list[SourceState]
    # 配信元の初回の読み込みが終わっていないとき True（その間は sources が空）
    loading: bool = False


@dataclass(frozen=True)
class NotServedItem:
    """検証に失敗した配信元の ID と理由。"""

    id: str
    errors: list[str]


@dataclass(frozen=True)
class ReloadResult:
    """`reload` の結果。"""

    added: list[str]
    removed: list[str]
    not_served: list[NotServedItem]
    sources: list[SourceState]


@dataclass(frozen=True)
class ScriptErrorItem:
    """実行できないスクリプト 1 つ。"""

    script: str
    reason: str


class CheckProjectRequest(BaseModel):
    """`check_project` の引数。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="配信元のフォルダか `project-index.yaml` の絶対パス")
    config: str | None = Field(
        default=None,
        description="ファイルに記載する前の `project-index.yaml` の中身（YAML の文字列）。省くとファイルを読み込む",
    )
    format: Literal["markdown", "json"] = Field(default="markdown", description="返却する形式")


@dataclass(frozen=True)
class CheckSync(SyncCounts):
    """同期の件数と、先頭 `SYNC_ITEMS_LIMIT` 件までの内訳。"""

    items: list[SyncItem] = field(default_factory=list[SyncItem])


@dataclass(frozen=True)
class CheckProjectResult:
    """`check_project` の結果。"""

    path: str
    registered_id: str | None
    config_version: str | None
    version_state: VersionState | None
    violations: list[Violation]
    missing_paths: list[str]
    script_errors: list[ScriptErrorItem]
    sync: CheckSync | None
    warnings: list[Violation] = field(default_factory=list[Violation])
    alias_schema_version: str = ""


class TryConvertRequest(BaseModel):
    """`try_convert` の引数。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="配信元のフォルダか `project-index.yaml` の絶対パス")
    file: str = Field(description="変換するファイルの、配信元からの相対パス")
    config: str | None = Field(
        default=None,
        description="ファイルに記載する前の `project-index.yaml` の中身（YAML の文字列）。省くとファイルを読み込む",
    )


@dataclass(frozen=True)
class TryConvertResult:
    """`try_convert` の結果。"""

    kind: str
    converter: str
    markdown: str


@dataclass(frozen=True)
class CandidateSource:
    """端末の設定によらずパスから読んだ配信元と、読んだときの違反。"""

    root: Path
    config_version: str | None
    violations: list[Violation]
    script_violations: list[Violation]
    source: ServedSource | None


class FormatRequest(BaseModel):
    """`status`・`reload` の引数。"""

    model_config = ConfigDict(extra="forbid")

    format: Literal["markdown", "json"] = Field(default="markdown", description="返却する形式")


class NavOperation(BaseModel):
    """`write_nav` の `operations` の 1 件。"""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add", "update", "remove"] = Field(description="追加・修正・削除")
    tab: str = Field(description="対象のタブの名前（`nav.tabs[].title`）")
    item: str | None = Field(
        default=None,
        description="タブの中の `group` の名前。入れ子は ` > ` で区切る。省くとタブそのもの",
    )
    value: dict[str, Any] | None = Field(
        default=None,
        description="タブか項目の中身（`nav` と同じ書式）。`add`・`update` で必須",
    )


class WriteNavRequest(BaseModel):
    """`write_nav` の引数。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="配信元のフォルダか `project-index.yaml` の絶対パス")
    operations: list[NavOperation] = Field(description="並べた順に適用する操作（1 件以上）")
    format: Literal["markdown", "json"] = Field(default="markdown", description="返却する形式")


@dataclass(frozen=True)
class WriteNavResult:
    """書いた `nav` と条件ごとの文書の数・警告。"""

    path: str
    nav: str
    counts: list[NavAutoCount]
    warnings: list[Violation]

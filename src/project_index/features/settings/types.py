"""端末の設定の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from project_index.features.sources.types import SourceStatus
from project_index.shared.api_model import ApiModel
from project_index.shared.errors import ProjectIndexError, Violation


class SourceScope(BaseModel):
    """`sources[].scope` の `read`・`write`。"""

    model_config = ConfigDict(extra="forbid")

    read: list[str] = Field(default_factory=list[str])
    write: list[str] | None = None


class SourceEntry(BaseModel):
    """端末の設定の `sources[]` の 1 行。"""

    model_config = ConfigDict(extra="forbid")

    config: list[str]
    id: str | None = None
    enabled: bool = True
    scope: SourceScope = SourceScope()
    outside_read: bool = True

    @field_validator("config", mode="before")
    @classmethod
    def _as_list(cls, value: Any) -> Any:  # noqa: ANN401
        """文字列 1 つで書かれたときも配列にする。"""
        return [value] if isinstance(value, str) else value


class SourcePatch(BaseModel):
    """1 行の変更で重ねるキー（送ったキーだけが `model_fields_set` に入る）。"""

    model_config = ConfigDict(extra="forbid")

    config: list[str] | None = None
    enabled: bool | None = None
    scope: SourceScope | None = None
    outside_read: bool | None = None

    @field_validator("config", mode="before")
    @classmethod
    def _as_list(cls, value: Any) -> Any:  # noqa: ANN401
        """文字列 1 つで書かれたときも配列にする。"""
        return [value] if isinstance(value, str) else value


class TerminalConfig(BaseModel):
    """検証を通して既定値を埋めた端末の設定。"""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    file: Path
    version: str
    clone: Path
    state_dir: Path
    log_dir: Path
    port: int = 8786
    bind: str = "127.0.0.1"
    sources: list[SourceEntry] = Field(default_factory=list[SourceEntry])
    seen_retention_days: int = 7
    script_timeout_sec: int = 30


class SettingsSourcesRequest(ApiModel):
    """PUT `/settings/sources` の本文。"""

    model_config = ConfigDict(extra="forbid")

    sources: list[SourceEntry]
    # 取得したときの端末の設定の内容のバージョン（`None` は照合しない）
    expected_version: str | None = None


class SettingsSourceAddRequest(ApiModel):
    """POST `/settings/sources` の本文。"""

    model_config = ConfigDict(extra="forbid")

    source: SourceEntry
    # 取得したときの端末の設定の内容のバージョン（`None` は照合しない）
    expected_version: str | None = None


class SettingsSourcePatchRequest(ApiModel):
    """PATCH `/settings/sources/{id}` の本文。"""

    model_config = ConfigDict(extra="forbid")

    # 取得したときの端末の設定の内容のバージョン（必須）
    expected_version: str
    source: SourcePatch


@dataclass(frozen=True)
class SourceAddResult:
    """配信元の 1 行の追加の戻り値。"""

    result: Literal["added", "exists"]
    # 同じ id の行の内容が同じか（`exists` のときだけ）
    same: bool | None = None
    # 読み直した後の配信元の状態（`added` のときだけ）
    statuses: list[SourceStatus] = field(default_factory=list[SourceStatus])
    # `added` は追加した後、`exists` は今の端末の設定の内容のバージョン
    version: str = ""


@dataclass(frozen=True)
class SourceWriteResult:
    """丸ごとの保存・1 行の変更・1 行の削除の戻り値。"""

    # 読み直した後の配信元の状態
    statuses: list[SourceStatus]
    # 書き換えた後の端末の設定の内容のバージョン
    version: str


class SourceViolation(ApiModel):
    """検証で除外した理由 1 件。"""

    path: str
    reason: str


class SourceConfigVersion(ApiModel):
    """設定のバージョンとサーバーが読み込めるバージョン。"""

    config: str
    server: str


class SettingsSourceStatus(ApiModel):
    """再読み込みした後の配信元 1 つの状態。"""

    id: str
    status: Literal["serving", "not_served", "disabled"]
    errors: list[SourceViolation] = Field(default_factory=list[SourceViolation])
    config_version: SourceConfigVersion | None = None


class SettingsSourcesResponse(ApiModel):
    """再読み込みした後の配信元ごとの状態。"""

    sources: list[SettingsSourceStatus]

    @classmethod
    def from_statuses(cls, statuses: list[SourceStatus]) -> SettingsSourcesResponse:
        """配信元の状態の並びから作る。"""
        items: list[SettingsSourceStatus] = []
        for status in statuses:
            item = SettingsSourceStatus(
                id=status.id,
                status=status.status,
                errors=(
                    [SourceViolation(path=v.path, reason=v.rule) for v in status.errors]
                    if status.status == "not_served"
                    else []
                ),
            )
            if status.config_version is not None:
                config, server = status.config_version
                item.config_version = SourceConfigVersion(config=config, server=server)
            items.append(item)
        return cls(sources=items)


class SettingsSourcesWriteResponse(SettingsSourcesResponse):
    """PUT `/settings/sources` と PATCH・DELETE `/settings/sources/{id}` の応答。"""

    # 書き換えた後の端末の設定の内容のバージョン
    version: str

    @classmethod
    def from_result(cls, result: SourceWriteResult) -> SettingsSourcesWriteResponse:
        """書き換えの結果から作る。"""
        return cls(
            sources=SettingsSourcesResponse.from_statuses(result.statuses).sources,
            version=result.version,
        )


class SettingsSourceAddResponse(ApiModel):
    """POST `/settings/sources` の応答。"""

    result: Literal["added", "exists"]
    same: bool | None = None
    sources: list[SettingsSourceStatus] = Field(default_factory=list[SettingsSourceStatus])
    version: str


class SettingsSourceRow(ApiModel):
    """端末の設定の取得の `sources[]` の 1 行（行の値に配信元の状態を重ねたもの）。"""

    id: str | None
    config: list[str]
    enabled: bool
    scope: SourceScope
    status: Literal["serving", "not_served", "disabled", "pending_reload"]
    errors: list[SourceViolation] = Field(default_factory=list[SourceViolation])
    config_version: SourceConfigVersion | None = None
    outside_read: bool


class SettingsSourcesView(ApiModel):
    """GET `/settings/sources` の応答。"""

    settings_path: str
    sources: list[SettingsSourceRow]
    # 行と同じ本文から求めた端末の設定の内容のバージョン
    version: str


@dataclass(kw_only=True)
class TerminalConfigInvalidError(ProjectIndexError):
    """端末の設定が無い・YAML として読めない・スキーマに違反すること。"""

    status: ClassVar[int] = 422
    file: Path = Path()
    violations: list[Violation] = field(default_factory=list[Violation])


@dataclass(kw_only=True)
class SettingsVersionMismatchError(ProjectIndexError):
    """要求の内容のバージョンが、今の端末の設定の内容のバージョンと違うこと。"""

    status: ClassVar[int] = 409
    current: str = ""


@dataclass(kw_only=True)
class SourceRowNotFoundError(ProjectIndexError):
    """1 行の変更・削除で指した ID の行が端末の設定に無いこと。"""

    status: ClassVar[int] = 404
    source_id: str = ""

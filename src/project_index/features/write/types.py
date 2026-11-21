"""書き込みと削除の要求・結果の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from project_index.features.access.types import CWD_DESCRIPTION
from project_index.features.search.types import Condition, Group
from project_index.features.validation.markdown import UncheckedKey
from project_index.shared.errors import Violation

OPERATIONS_MAX = 50


@dataclass(frozen=True, slots=True, kw_only=True)
class WriteViolation(Violation):
    """スキーマの説明を持てる書き込みの違反。"""

    # 違反した項目のスキーマの定義から取り出した説明（`title`・`description` など）
    schema: dict[str, Any] | None = None


class TextEdit(BaseModel):
    """文字列の項目の一部を置き換える操作。"""

    model_config = ConfigDict(extra="forbid")

    field: str
    old: str
    new: str
    replace_all: bool = False


class Operation(BaseModel):
    """`write_docs` の `operations` の 1 件。"""

    model_config = ConfigDict(extra="forbid")

    op: Literal["create", "update", "replace", "rename", "replace_text"]
    kind: str | None = None
    id: str | None = None
    expected_version: str | dict[str, str] | None = None
    data: dict[str, Any] | None = None
    set: dict[str, Any] = Field(default_factory=dict[str, Any])
    unset: list[str] = Field(default_factory=list[str])
    add_to: dict[str, list[Any]] = Field(default_factory=dict[str, list[Any]])
    remove_from: dict[str, list[Any]] = Field(default_factory=dict[str, list[Any]])
    text_edits: list[TextEdit] = Field(default_factory=list[TextEdit])
    new_id: str | None = None
    new_path: str | None = None
    filter: Condition | Group | None = None
    old: str | None = None
    new: str | None = None
    fields: list[str] | None = None


class CommitSpec(BaseModel):
    """`write_docs`・`delete_docs` の `commit`。"""

    model_config = ConfigDict(extra="forbid")

    message: str
    # `None` は配信元の設定の `direct_commit.branch`
    branch: str | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        """空白だけの説明を断る。"""
        if not value.strip():
            message = "コミットの説明が空です"
            raise ValueError(message)
        return value


@dataclass(frozen=True)
class CommitResult:
    """直コミットでプッシュしたコミット。"""

    sha: str
    branch: str
    # プッシュが 1 回断られ、取得からやり直したか
    retried: bool


class WriteRequest(BaseModel):
    """`write_docs` の引数。"""

    model_config = ConfigDict(extra="forbid")

    operations: list[Operation]
    source: str | None = None
    worktree: str | None = None
    atomic: bool = True
    dry_run: bool = False
    cwd: str | None = Field(default=None, description=CWD_DESCRIPTION)
    session_id: str | None = None
    agent_id: str | None = None
    # 直コミット。`None` はコミットとプッシュをしない
    commit: CommitSpec | None = None


@dataclass(frozen=True)
class ReferenceChange:
    """`rename` で書き換えた参照元の 1 か所。"""

    path: str
    before: str
    after: str


@dataclass(frozen=True)
class SkippedOperation:
    """違反にせず何もしなかった `unset` の要素・`remove_from` のキー 1 件。"""

    path: str
    reason: str


@dataclass(frozen=True)
class WriteResultItem:
    """操作 1 件の結果。"""

    index: int
    id: str | None
    status: Literal["created", "updated", "replaced", "renamed", "deleted", "failed"]
    version: str | None = None
    diff: str | None = None
    errors: list[Violation] = field(default_factory=list[Violation])
    unchecked: list[UncheckedKey] = field(default_factory=list[UncheckedKey])
    skipped: list[SkippedOperation] = field(default_factory=list[SkippedOperation])
    path: str | None = None
    renamed_from: str | None = None
    references: list[ReferenceChange] = field(default_factory=list[ReferenceChange])
    count: int | None = None


@dataclass(frozen=True)
class WriteResult:
    """`write_docs` が返すもの。"""

    applied: bool
    results: list[WriteResultItem]
    # `commit` を指定し `dry_run: false` で書き込んだときだけ
    commit: CommitResult | None = None


class DeleteTarget(BaseModel):
    """`delete_docs` の `targets` の 1 件。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    expected_version: str


class DeleteRequest(BaseModel):
    """`delete_docs` の引数。"""

    model_config = ConfigDict(extra="forbid")

    targets: list[DeleteTarget]
    source: str | None = None
    worktree: str | None = None
    on_referenced: Literal["fail", "unlink"] = "fail"
    atomic: bool = True
    dry_run: bool = False
    cwd: str | None = Field(default=None, description=CWD_DESCRIPTION)
    commit: CommitSpec | None = None


@dataclass(frozen=True)
class DeleteResult:
    """`delete_docs` が返すもの。"""

    applied: bool
    results: list[WriteResultItem]
    unlinked: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    commit: CommitResult | None = None

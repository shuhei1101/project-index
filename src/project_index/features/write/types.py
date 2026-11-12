"""書き込みと削除の要求・結果の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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

    op: Literal["create", "update", "replace"]
    kind: str | None = None
    id: str | None = None
    expected_version: str | dict[str, str] | None = None
    data: dict[str, Any] | None = None
    set: dict[str, Any] = Field(default_factory=dict[str, Any])
    unset: list[str] = Field(default_factory=list[str])
    add_to: dict[str, list[Any]] = Field(default_factory=dict[str, list[Any]])
    remove_from: dict[str, list[Any]] = Field(default_factory=dict[str, list[Any]])
    text_edits: list[TextEdit] = Field(default_factory=list[TextEdit])


class WriteRequest(BaseModel):
    """`write_docs` の引数。"""

    model_config = ConfigDict(extra="forbid")

    operations: list[Operation]
    source: str | None = None
    worktree: str | None = None
    atomic: bool = True
    dry_run: bool = False
    cwd: str | None = None
    session_id: str | None = None
    agent_id: str | None = None


@dataclass(frozen=True)
class WriteResultItem:
    """操作 1 件の結果。"""

    index: int
    id: str | None
    status: Literal["created", "updated", "replaced", "deleted", "failed"]
    version: str | None = None
    diff: str | None = None
    errors: list[Violation] = field(default_factory=list[Violation])
    unchecked: list[UncheckedKey] = field(default_factory=list[UncheckedKey])


@dataclass(frozen=True)
class WriteResult:
    """`write_docs` が返すもの。"""

    applied: bool
    results: list[WriteResultItem]


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
    cwd: str | None = None


@dataclass(frozen=True)
class DeleteResult:
    """`delete_docs` が返すもの。"""

    applied: bool
    results: list[WriteResultItem]
    unlinked: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])

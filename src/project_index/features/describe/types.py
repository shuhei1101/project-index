"""説明の要求と結果の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from project_index.features.access.types import SourceAccess, Workplace
from project_index.features.history.types import WorktreeInfo


class DescribeRequest(BaseModel):
    """`describe` の引数。"""

    model_config = ConfigDict(extra="forbid")

    source: str | None = None
    kind: str | None = None
    worktree: str | None = None
    format: Literal["markdown", "json"] = "markdown"
    cwd: str | None = None
    outside_scope: bool = Field(
        default=False,
        description=(
            "true のとき、scope に該当しない配信元を outside_read が真なら"
            "作業範囲の外（参考）として参照する（source が ID 1 つのとき）。"
            "source を省くと、使用できる配信元の一覧に作業範囲の外で参照できる配信元の一覧を加える"
        ),
    )


@dataclass(frozen=True)
class KindSummary:
    """種類の一覧の 1 行。"""

    id: str
    description: str


@dataclass(frozen=True)
class OutsideSource:
    """作業範囲の外で読める配信元の一覧の 1 行。"""

    id: str
    description: str


@dataclass(frozen=True)
class SourceListResult:
    """引数なしの結果。"""

    workplace: Workplace
    sources: list[SourceAccess]
    # `outside_scope` を渡したときだけ持つ（0 件は空のリスト）
    outside_sources: list[OutsideSource] | None = None
    warnings: list[str] = field(default_factory=list[str])


@dataclass(frozen=True)
class SourceGuideResult:
    """`source` だけの結果。"""

    source_id: str
    instructions: str
    kinds: list[KindSummary]
    outside_scope: bool = False
    refs: dict[str, list[str]] | None = None
    worktrees: list[WorktreeInfo] | None = None


@dataclass(frozen=True)
class KindSchemaResult:
    """`source`・`kind` の結果。"""

    source_id: str
    kind: str
    schema_text: str
    schema: dict[str, Any]
    metadata: dict[str, str] = field(default_factory=dict[str, str])
    outside_scope: bool = False

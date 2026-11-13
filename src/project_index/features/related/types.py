"""関連のたどりの要求と結果の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from project_index.features.access.types import CWD_DESCRIPTION

DEPTH_DEFAULT = 2
DEPTH_MAX = 4
SUGGEST_COUNT = 3


class RelatedRequest(BaseModel):
    """`trace_related` の引数。"""

    model_config = ConfigDict(extra="forbid")

    source: str | None = None
    ref: str | None = None
    worktree: str | None = None
    from_ids: list[str] | None = None
    code_paths: list[str] | None = None
    depth: int = DEPTH_DEFAULT
    direction: Literal["out", "in", "both"] = "both"
    suggest: bool = False
    repeat_seen: bool = False
    format: Literal["markdown", "json"] = "markdown"
    cwd: str | None = Field(default=None, description=CWD_DESCRIPTION)
    outside_scope: bool = Field(
        default=False,
        description=(
            "true のとき、scope に該当しない配信元を outside_read が真なら"
            "作業範囲の外（参考）として参照する（source が ID 1 つのときだけ有効）"
        ),
    )
    session_id: str | None = None
    agent_id: str | None = None


@dataclass(frozen=True)
class RelatedLink:
    """メタデータの `related` の 1 行。"""

    to: str
    type: str
    source: str | None = None


@dataclass(frozen=True)
class RelatedItem:
    """たどった 1 件の文書。"""

    id: str
    source: str | None
    depth: int
    via_from: str
    via_type: str
    via_direction: Literal["out", "in"]
    name: str
    description: str
    # 文書の場所と返した範囲。`ref` を渡した呼び出し・返し済みの相手・読めない配信元の文書では `None`
    path: str | None = None
    scope: Literal["summary"] | None = None


@dataclass(frozen=True)
class Suggestion:
    """まだ `related` に無い関連の候補。"""

    id: str
    signals: list[Literal["co_change", "edited", "viewed"]]
    score: float


@dataclass(frozen=True)
class RelatedResult:
    """`trace_related` が返すもの。"""

    start: list[str]
    items: list[RelatedItem] = field(default_factory=list[RelatedItem])
    suggestions: list[Suggestion] = field(default_factory=list[Suggestion])
    notes: list[str] = field(default_factory=list[str])
    outside_scope: bool = False

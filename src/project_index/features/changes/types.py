"""変更の一覧の要求と結果の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from project_index.features.search.types import LIMIT_DEFAULT, MAX_CHARS_DEFAULT, Condition, Group

LAST_READ_LABEL = "前回読んだ時点"
WORKTREE_LABEL = "作業ツリー"


class ContainsQuery(BaseModel):
    """`list_changes` の `contains`（変更の中身の単語）。"""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, description="探す単語か正規表現")
    regex: bool = Field(default=False, description="value を正規表現として適用するか")
    case_sensitive: bool = Field(
        default=False, description="大文字小文字と全角半角（NFKC）を区別するか"
    )


class ChangesRequest(BaseModel):
    """`list_changes` の引数。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str | list[str] | None = None
    worktree: str | None = None
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    filter: Condition | Group | None = None
    view: Literal["summary", "full"] = "summary"
    limit: int = LIMIT_DEFAULT
    cursor: str | None = None
    max_chars: int = MAX_CHARS_DEFAULT
    format: Literal["markdown", "json"] = "markdown"
    cwd: str | None = None
    outside_scope: bool = Field(
        default=False,
        description=(
            "true のとき、scope に該当しない配信元を outside_read が真なら"
            "作業範囲の外（参考）として参照する（source が ID 1 つのときだけ有効）"
        ),
    )
    session_id: str | None = None
    agent_id: str | None = None
    contains: ContainsQuery | None = Field(
        default=None,
        description=(
            "単語の出現数が変わった文書だけを返却し、単語が入った・消えた区間を添える。"
            "filter と同時に指定すると両方に該当する文書を返却する"
        ),
    )


@dataclass(frozen=True)
class RangePoint:
    """区間の始点か終点。"""

    input: str
    commit: str | None = None
    date: datetime | None = None


@dataclass(frozen=True)
class ContainsChange:
    """語の出現数が変わった区間 1 つ。"""

    # 出現数が増えた（added）か減った（removed）か
    kind: Literal["added", "removed"]
    # 区間の前の端（親の commit）
    from_: RangePoint
    # 区間の後の端（語が入った・消えた commit か作業ツリー）
    to: RangePoint
    # 前と後の端の文書の出現数（文書が無ければ 0）
    count_before: int
    count_after: int


@dataclass(frozen=True)
class ChangeItem:
    """変わった文書 1 件。"""

    id: str
    source: str | None
    change: Literal["added", "modified", "deleted", "unchanged"]
    keys: list[str]
    values: dict[str, tuple[Any, Any]] = field(default_factory=dict[str, tuple[Any, Any]])
    diff: str | None = None
    # 変わった文書の今の場所と返した範囲。`to` を渡した呼び出しと `deleted` では `None`
    path: str | None = None
    scope: Literal["section", "summary"] | None = None
    # 語の出現数が変わった区間の古い順。`contains` を渡したときだけ持つ
    contains_changes: list[ContainsChange] | None = None


@dataclass(frozen=True)
class ChangesResult:
    """`list_changes` が返すもの。"""

    range_from: RangePoint
    range_to: RangePoint
    total_count: int
    items: list[ChangeItem] = field(default_factory=list[ChangeItem])
    next_cursor: str | None = None
    truncated: bool = False
    notes: list[str] = field(default_factory=list[str])
    outside_scope: bool = False

"""検索の要求と結果の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from project_index.features.documents.types import MatchWord

LIMIT_DEFAULT = 20
LIMIT_MAX = 100
MAX_CHARS_DEFAULT = 20000
MAX_CHARS_LIMIT = 40000
FIELD_CHARS_DEFAULT = 2000
FIELD_CHARS_FULL = 10000
SUMMARY_FIELDS = ("kind", "name", "description", "@chars", "version")


class Condition(BaseModel):
    """1 つの項目を比べる条件。"""

    model_config = ConfigDict(extra="forbid")

    field: str
    op: Literal[
        "eq",
        "ne",
        "prefix",
        "suffix",
        "contains",
        "not_contains",
        "regex",
        "glob",
        "gt",
        "gte",
        "lt",
        "lte",
        "exists",
        "not_exists",
    ] = Field(
        description=(
            "比べ方。regex は値の各行に適用する"
            "（^・$ は各行の先頭・末尾。値全体の先頭・末尾は \\A・\\Z）。"
            "glob は値全体に適用し、** は / をまたぎ、*・? は / をまたがない"
        )
    )
    values: list[str] = Field(default_factory=list[str])
    match: Literal["any", "all"] = "any"
    case_sensitive: bool = Field(
        default=False,
        description=(
            "False は NFKC と casefold をした後に比べる"
            "（regex はパターンに正規化をかけず、re.IGNORECASE と NFKC にした値で比べる）"
        ),
    )


class Group(BaseModel):
    """条件を AND・OR でまとめるか、否定する。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    all_of: list[Condition | Group] | None = Field(default=None, alias="and")
    any_of: list[Condition | Group] | None = Field(default=None, alias="or")
    not_: Condition | Group | None = Field(
        default=None,
        alias="not",
        description="中の条件か束に該当しない文書に該当する。and・or の中にも配置できる",
    )


class OrderKey(BaseModel):
    """並べ替えの 1 つのキー。"""

    model_config = ConfigDict(extra="forbid")

    field: str
    direction: Literal["asc", "desc"] = "asc"


class Snippets(BaseModel):
    """本文の代わりに条件に該当した行と前後の行だけを行番号つきで返却する指定。"""

    model_config = ConfigDict(extra="forbid")

    context_lines: int = Field(
        default=1, description="before・after を省いたときの前と後ろの行の数（0〜10）"
    )
    max_per_doc: int = Field(default=3, description="1 つの文書で返却する箇所の数（1〜20）")
    before: int | None = Field(
        default=None, ge=0, description="該当した行の前に返却する行の数。省けば context_lines"
    )
    after: int | None = Field(
        default=None, ge=0, description="該当した行の後ろに返却する行の数。省けば context_lines"
    )


class LineRange(BaseModel):
    """本文から返却する行の範囲。"""

    model_config = ConfigDict(extra="forbid")

    offset: int = Field(default=1, ge=1, description="返却する最初の行の行番号（1 始まり）")
    limit: int | None = Field(
        default=None, ge=1, description="返却する行の数。省けば本文の末尾まで"
    )


class SearchRequest(BaseModel):
    """`search_docs` の引数。"""

    model_config = ConfigDict(extra="forbid")

    source: str | list[str] | None = None
    ref: str | None = None
    worktree: str | None = None
    filter: Condition | Group | None = None
    term: str | None = Field(
        default=None,
        description="alias_type を持つ行の文書のうち、name か aliases がこの単語に一致する文書だけに絞る",
    )
    view: Literal["ids", "summary", "full", "count"] = "summary"
    fields: list[str] = Field(default_factory=list[str])
    exclude_fields: list[str] = Field(default_factory=list[str])
    order_by: list[OrderKey] | None = None
    group_by: str | None = None
    limit: int = LIMIT_DEFAULT
    cursor: str | None = None
    skip: int = 0
    max_chars: int = MAX_CHARS_DEFAULT
    max_chars_per_field: int | None = None
    snippets: Snippets | None = None
    repeat_seen: bool = False
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
    sections: list[str] | None = Field(
        default=None,
        description=(
            "Markdown の本文から返却するセクションの見出しの文字列"
            "（# と前後の空白を除いた文字列と完全一致）。view: full のときだけ。lines と同時に指定できない"
        ),
    )
    lines: LineRange | None = Field(
        default=None,
        description="本文から返却する行の範囲。view: full のときだけ。sections と同時に指定できない",
    )


@dataclass(frozen=True)
class SnippetLine:
    """抜粋の 1 行。"""

    # 本文の行番号（1 始まり）
    line: int
    # 行の文字列（改行を含まない）
    text: str
    # 当たった行なら True、前後の行なら False
    hit: bool


@dataclass(frozen=True)
class Snippet:
    """重なる範囲をまとめた 1 つの抜粋。"""

    lines: list[SnippetLine]


@dataclass(frozen=True)
class BodyRange:
    """本文の行の範囲 1 つ。"""

    # 本文の行番号（1 始まり）
    start_line: int
    # 本文の行番号（1 始まり、この行を含む）
    end_line: int


@dataclass(frozen=True)
class Heading:
    """Markdown の本文の見出し 1 つ。"""

    # 本文の行番号（1 始まり）
    line: int
    # `#` の数（1〜6）
    level: int
    # `#` と前後の空白、末尾の閉じの `#` を除いた文字列
    text: str


@dataclass(frozen=True)
class SearchItem:
    """返す 1 件の文書の項目。"""

    id: str
    source: str | None
    values: dict[str, Any]
    snippets: list[Snippet] = field(default_factory=list[Snippet])
    # 文書の場所と返した範囲。`ref` を渡した呼び出し・返し済み・本文を扱わない view では `None`
    path: str | None = None
    scope: Literal["full", "section", "summary"] | None = None
    # `sections`・`lines` で切り出した本文の行の範囲（渡さない呼び出しでは `None`、範囲が無ければ空）
    ranges: list[BodyRange] | None = None
    # 本文の全体の行数（`ranges` と同じ条件で持つ）
    total_lines: int | None = None


@dataclass(frozen=True)
class GroupCount:
    """`group_by` の値ごとの件数。"""

    value: str
    count: int


@dataclass(frozen=True)
class SearchResult:
    """`search_docs` が返すもの。"""

    total_count: int
    returned: int
    view: str
    per_source: dict[str, int] = field(default_factory=dict[str, int])
    next_cursor: str | None = None
    truncated: bool = False
    notes: list[str] = field(default_factory=list[str])
    groups: list[GroupCount] = field(default_factory=list[GroupCount])
    items: list[SearchItem] = field(default_factory=list[SearchItem])
    # Markdown の先頭に出す配信元の ID。JSON には出さない
    source_label: str = field(default="", metadata={"internal": True})
    outside_scope: bool = False


class MatchWordsRequest(BaseModel):
    """`list_match_words` の引数。"""

    model_config = ConfigDict(extra="forbid")

    source: str
    worktree: str | None = None
    format: Literal["markdown", "json"] = "markdown"
    cwd: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MatchWordsResult:
    """照合する語の並び。"""

    words: list[MatchWord] = field(default_factory=list[MatchWord])

"""読み取り API の型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from project_index.shared.api_model import ApiModel


class NavItem(ApiModel):
    """サイドバーの見出しか文書の 1 行。"""

    kind: Literal["group", "page"]
    title: str
    path: str | None = None
    items: list[NavItem] = Field(default_factory=lambda: list[NavItem]())


class NavTab(ApiModel):
    """上のタブ 1 つとそのサイドバー。"""

    title: str
    items: list[NavItem]


class ConversionError(ApiModel):
    """文書の取得の `conversionError`（変換の失敗と同じフィールド）。"""

    reason: Literal["timeout", "exit", "not_runnable", "invalid_yaml"]
    kind: str
    script: str | None = None
    detail: str
    file: str | None = None
    line: int | None = None
    column: int | None = None


class GitHubTarget(ApiModel):
    """配信元の設定の `github`（起票先）。"""

    repository: str
    issue_labels: list[str]


class SearchItem(ApiModel):
    """語での検索の結果の文書。"""

    path: str
    id: str
    file_path: str
    name: str
    snippets: list[str]


class SearchResult(ApiModel):
    """GET `/sources/{source}/search` の応答。"""

    total_count: int
    items: list[SearchItem]


class RefItem(ApiModel):
    """ブランチかタグ 1 つ。"""

    name: str
    commit: str


class CommitItem(ApiModel):
    """最近の commit 1 件。"""

    commit: str
    date: str
    subject: str


class RefsResponse(ApiModel):
    """GET `/sources/{source}/refs` の応答。"""

    git: bool
    default_ref: str
    branches: list[RefItem] = Field(default_factory=list[RefItem])
    tags: list[RefItem] = Field(default_factory=list[RefItem])
    commits: list[CommitItem] = Field(default_factory=list[CommitItem])


class SourceConfigResponse(ApiModel):
    """GET `/sources/{source}/config` の応答。"""

    nav: dict[str, Any] | None
    documents: list[dict[str, Any]]
    decisions: dict[str, list[str]]
    github: GitHubTarget | None
    # 中のキー `ignore_keys` は配信元の設定から写したまま camelCase にしないため辞書で持つ
    diff: dict[str, list[str]]
    schemas: dict[str, dict[str, Any]] | None = None


class DocumentListItem(ApiModel):
    """文書の一覧の 1 件と、文書の取得のメタデータ。"""

    id: str
    path: str
    kind: str
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list[str])
    visibility: str | None = None
    body_path: str | None = None


class DocumentListEntry(DocumentListItem):
    """文書の一覧の 1 件。文書の取得のメタデータに無いバージョンと値を持つ。"""

    version: str
    value: dict[str, Any] | None = None


class DocumentListResponse(ApiModel):
    """GET `/sources/{source}/docs` の応答。"""

    ref: str
    documents: list[DocumentListEntry]


class DocumentValueResponse(ApiModel):
    """GET `/sources/{source}/docs/{path}` の応答。"""

    source: str
    ref: str
    path: str
    value: dict[str, Any] | None
    # `schema` は BaseModel の属性と重なるため、Python の名前を変えて JSON のキーだけ `schema` にする
    schema_: dict[str, Any] | None = Field(alias="schema")
    metadata: DocumentListItem | None
    body: str | None = None
    body_path: str | None = None
    markdown: str | None = None
    conversion_error: ConversionError | None = None
    updated_at: datetime


class DecisionItem(ApiModel):
    """検討事項の ID の一覧の 1 件。"""

    id: str
    folders: int


class DecisionListResponse(ApiModel):
    """GET `/sources/{source}/decisions` の応答。"""

    decisions: list[DecisionItem]


class DecisionResponse(ApiModel):
    """GET `/sources/{source}/decisions/{id}` の応答。"""

    id: str
    folder: str
    body: str


@dataclass(frozen=True, slots=True, kw_only=True)
class NavAutoCount:
    """`nav` の `auto` 1 つと、その条件に当たる文書の数。"""

    path: str
    tab: str
    filter: dict[str, Any] | None
    count: int

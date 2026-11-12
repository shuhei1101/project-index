"""リビジョンと変更の型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class ResolvedRef:
    """渡されたリビジョンと、解いた commit とその日時。"""

    input: str
    commit: str
    date: datetime


@dataclass(frozen=True)
class NamedRef:
    """ブランチかタグの名前と commit。"""

    name: str
    commit: str


@dataclass(frozen=True)
class CommitSummary:
    """最近の commit 1 つ。"""

    commit: str
    date: str
    subject: str


@dataclass(frozen=True)
class RefList:
    """リビジョンの一覧。"""

    git: bool
    default_ref: str
    branches: list[NamedRef] = field(default_factory=list[NamedRef])
    tags: list[NamedRef] = field(default_factory=list[NamedRef])
    commits: list[CommitSummary] = field(default_factory=list[CommitSummary])


@dataclass(frozen=True)
class FileChange:
    """区間で変わったファイル 1 つ。"""

    path: str
    change: Literal["added", "modified", "deleted"]


@dataclass(frozen=True)
class CommitStep:
    """区間の中の commit 1 つと、最初の親。"""

    commit: str
    date: datetime
    parent: str
    parent_date: datetime


@dataclass(frozen=True)
class FileDates:
    """ファイルが最初に入った commit と最後に変わった commit の日時。"""

    created: datetime
    updated: datetime


@dataclass(frozen=True)
class WorktreeInfo:
    """ワークツリーのパスと checkout しているブランチ。"""

    path: str
    branch: str | None

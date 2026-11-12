"""作業場所からの権限と読み書きの場所の型。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from project_index.features.sources.types import ServedSource

AccessLevel = Literal["read", "write"]

# 文書の MCP のツールの入力のスキーマで、`cwd` の説明に入れる文
CWD_DESCRIPTION = (
    "作業場所。PreToolUse のフックがセッションの作業場所で上書きするため、指定しても使わない。"
    "ワークツリーを指すときは worktree を指定する"
)


@dataclass(frozen=True)
class SourceAccess:
    """今の作業場所から使える配信元 1 つと権限。"""

    source_id: str
    access: AccessLevel
    current: bool
    description: str


@dataclass(frozen=True)
class Workplace:
    """作業場所がどの配信元のクローン本体かワークツリーか。"""

    cwd: Path | None
    source_id: str | None
    worktree: Path | None


@dataclass(frozen=True)
class Target:
    """1 つの配信元をどこから読み書きするか。"""

    source: ServedSource
    base: Path
    ref: str | None
    worktree: Path | None
    access: AccessLevel
    outside_scope: bool = False
    commit: str | None = None


def script_at(target: Target) -> tuple[Path, str] | None:
    """クローン本体で動かすスクリプトを取り出す commit（クローン本体と `config_commit`）を返す。"""
    source = target.source
    if target.worktree is not None or source.main_root is None or source.config_commit is None:
        return None
    return source.main_root, source.config_commit

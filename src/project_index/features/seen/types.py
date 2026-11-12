"""会話キーと会話ごとの記録の型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

SEEN_MARK = "（この会話で返却済み）"

type ReturnKind = Literal["body", "related"]
type ActivityKind = Literal["viewed", "edited"]


@dataclass(frozen=True)
class SessionKey:
    """記録を分ける会話の単位。"""

    session_id: str
    agent_id: str = ""

    @classmethod
    def of(cls, session_id: str | None, agent_id: str | None) -> SessionKey | None:
        """ツールの引数から会話キーを作る。"""
        if not session_id:
            return None
        return cls(session_id, agent_id or "")


@dataclass(frozen=True)
class LastRead:
    """この会話で最後に本文を返したときの文書。"""

    doc_id: str
    version: str
    doc_kind: str
    content: str
    read_at: datetime


@dataclass(frozen=True)
class Activity:
    """会話の中で文書を閲覧・編集したこと。"""

    doc_id: str
    kind: ActivityKind
    at: datetime

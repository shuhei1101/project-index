"""`POST /_admin/session-start` の本文と応答の型と、返し済みの記録を削除する理由。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 返し済みの記録を削除する `reason`
FORGET_REASONS = frozenset({"clear", "compact"})


class SessionStartRequest(BaseModel):
    """SessionStart のフックが送信する本文。"""

    # フックの入力に増えたキーを断らないよう、知らないキーは捨てる
    model_config = ConfigDict(extra="ignore")

    session_id: str = Field(description="Claude Code のセッション ID")
    agent_id: str | None = Field(default=None, description="サブエージェントの ID")
    reason: Literal["startup", "resume", "clear", "compact", "fork"] = Field(
        description="SessionStart の入力の `source`"
    )


class SessionStartResponse(BaseModel):
    """返却済みの記録を削除したか。"""

    forgotten: bool = Field(description="返却済みの記録を削除したか")

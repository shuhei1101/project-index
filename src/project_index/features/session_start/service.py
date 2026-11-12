"""`/clear`・圧縮の後の、返し済みの記録の削除。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from project_index.features.seen.types import SessionKey
from project_index.features.session_start.types import (
    FORGET_REASONS,
    SessionStartRequest,
    SessionStartResponse,
)

if TYPE_CHECKING:
    from project_index.features.seen.store import SeenStore

logger = logging.getLogger(__name__)


def start_session(request: SessionStartRequest, *, seen: SeenStore) -> SessionStartResponse:
    """`reason` が `FORGET_REASONS` なら、その会話キーの返し済みの記録を削除する。"""
    key = SessionKey.of(request.session_id, request.agent_id)
    if request.reason not in FORGET_REASONS or key is None:
        return SessionStartResponse(forgotten=False)
    removed = seen.forget(key)
    logger.info("返し済みの記録を削除した（%s・%s 件）", request.session_id, removed)
    return SessionStartResponse(forgotten=True)

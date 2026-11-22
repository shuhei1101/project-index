"""画面のサーバーが呼ぶ書き込みの API（`POST /sources/{source}/commits`）のルート。"""

from __future__ import annotations

import functools
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from project_index.features.write.service import commit_documents
from project_index.features.write.types import CommitDocumentsBody, CommitDocumentsResponse
from project_index.server.origin import require_same_origin
from project_index.shared.deadline import CallLimits, Deadline

if TYPE_CHECKING:
    from project_index.features.write.types import CommitDocumentsRequest, CommitDocumentsResult
    from project_index.main import Handlers

# 応答の上限（文書の MCP のツールの応答の上限と同じ）
RESPONSE_LIMIT_SEC = 48


def _commit(
    handlers: Handlers, request: CommitDocumentsRequest, limits: CallLimits
) -> CommitDocumentsResult:
    """書き込みと削除の直コミットを、配線済みの部品で呼ぶ。"""
    return commit_documents(
        request,
        registry=handlers.registry,
        store=handlers.store,
        checker=handlers.checker,
        locks=handlers.locks,
        repo_locks=handlers.repo_locks,
        timeout_sec=handlers.terminal.script_timeout_sec,
        limits=limits,
    )


def build_write_router(handlers: Handlers) -> APIRouter:
    """書き込みの API のルートを持つルーターを作る。"""
    router = APIRouter(tags=["write"], dependencies=[Depends(require_same_origin)])

    @router.post("/sources/{source}/commits", name="commit_documents")
    async def commit_documents_route(
        source: str, body: CommitDocumentsBody
    ) -> CommitDocumentsResponse:
        # 期限は要求を受けた時刻から数える
        started = time.monotonic()
        limits = CallLimits(
            write_deadline=Deadline(
                limit_sec=handlers.terminal.write_deadline_sec, started=started
            ),
            respond_by=Deadline(limit_sec=RESPONSE_LIMIT_SEC, started=started),
        )
        with handlers.slots.request("commit_documents", source=source):
            # 読み込みを待つ間も要求の応答中として数え、裏の検査と書き出しを休ませる
            with handlers.gate.foreground():
                await handlers.registry.wait_for(ids=[source])
            with handlers.gate.foreground():
                result = await handlers.slots.run_docs(
                    functools.partial(_commit, handlers, body.to_request(source), limits)
                )
        return CommitDocumentsResponse.from_domain(result)

    return router

"""画面のサーバーが呼ぶ書き込みの API（`POST /sources/{source}/commits`）のルート。"""

from __future__ import annotations

import functools
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from project_index.features.admin.service import reload_config
from project_index.features.write.service import commit_documents
from project_index.features.write.source_config import read_source_config_file
from project_index.features.write.types import (
    CommitDocumentsBody,
    CommitDocumentsResponse,
    SourceConfigFileResponse,
)
from project_index.server.error_handlers import problem_of
from project_index.server.origin import require_same_origin
from project_index.shared.deadline import CallLimits, Deadline
from project_index.shared.errors import SourceNotServedError, UnknownSourceError

if TYPE_CHECKING:
    from project_index.features.write.types import CommitDocumentsRequest, CommitDocumentsResult
    from project_index.main import Handlers

# 書き込みの API の応答の上限（dev-docs が書き込みの API を待つ上限 45 秒 × 0.8）
WRITE_API_RESPONSE_LIMIT_SEC = 36
# 書き込みの API の書き込みの期限（応答の上限から、生成とコミット・プッシュ・照合と応答の組み立ての秒数を除く）
WRITE_API_WRITE_DEADLINE_SEC = 20


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
        state_dir=handlers.terminal.state_dir,
        # 配信元の設定をプッシュした後は、管理の MCP の reload と同じに再読み込みする
        reload_sources=functools.partial(reload_config, handlers),
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
            write_deadline=Deadline(limit_sec=WRITE_API_WRITE_DEADLINE_SEC, started=started),
            respond_by=Deadline(limit_sec=WRITE_API_RESPONSE_LIMIT_SEC, started=started),
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

    @router.get(
        "/sources/{source}/config/file",
        name="get_source_config_file",
        response_model=SourceConfigFileResponse,
    )
    def get_source_config_file(source: str) -> SourceConfigFileResponse | JSONResponse:
        try:
            served = handlers.registry.get_for_docs(source)
        except UnknownSourceError as error:
            # 端末の設定に無い配信元: 読み取り API と同じ missing を添えた 404
            return problem_of(error, {"missing": "source", "value": error.source_id})
        except SourceNotServedError as error:
            # 配信していない配信元: 読み取り API と同じ missing を添えた 404
            return problem_of(error, {"missing": "not_served", "value": source})
        # 書き換える前の project-index.yaml を、コミットするブランチのワークツリーから返す
        return SourceConfigFileResponse.from_domain(read_source_config_file(served))

    return router

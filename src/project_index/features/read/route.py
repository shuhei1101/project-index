"""読み取り API のルート（`/sources` の下）。"""

from __future__ import annotations

import asyncio
import dataclasses
from functools import partial
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Query
from fastapi.responses import Response

from project_index.features.history.query import list_refs
from project_index.features.read.paths import read_target
from project_index.features.read.search import (
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    SEARCH_QUERY_MAX,
    search_words,
)
from project_index.features.read.service import (
    get_decision,
    get_document,
    get_source_config,
    list_decisions,
    list_documents,
)
from project_index.features.read.types import (
    DecisionListResponse,
    DecisionResponse,
    DocumentListResponse,
    DocumentValueResponse,
    RefsResponse,
    SearchResult,
    SourceConfigResponse,
)
from project_index.features.settings.types import SettingsSourcesResponse
from project_index.server.error_handlers import problem_of
from project_index.shared.errors import (
    DecisionNotFoundError,
    DocumentNotFoundError,
    ProjectIndexError,
    RefNotFoundError,
    SourceNotServedError,
    UnknownSourceError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_index.main import Handlers

REFS_COMMITS_DEFAULT = 20
REFS_COMMITS_MAX = 100


def _not_found_fields(
    error: ProjectIndexError, source_id: str, value: str
) -> dict[str, str] | None:
    """404 の problem+json に加える `missing` と `value` を作る（404 にしないエラーは `None`）。"""
    if isinstance(error, UnknownSourceError):
        return {"missing": "source", "value": error.source_id}
    if isinstance(error, SourceNotServedError):
        return {"missing": "not_served", "value": source_id}
    if isinstance(error, RefNotFoundError):
        return {"missing": "ref", "value": error.value}
    if isinstance(error, DocumentNotFoundError | DecisionNotFoundError):
        return {"missing": "doc", "value": value}
    return None


async def _run[T](
    handlers: Handlers, source: str, value: str, work: Callable[[], T]
) -> T | Response:
    """配信元の読み込みを待って処理を別のスレッドで呼び、見つからなかったものを 404 にする。"""
    await handlers.registry.wait_for(ids=[source])
    try:
        return await asyncio.to_thread(work)
    except ProjectIndexError as error:
        fields = _not_found_fields(error, source, value)
        # 404 にしないエラー: 例外の変換に任せる
        if fields is None:
            raise
        return problem_of(error, fields)


def _source_config(handlers: Handlers, source: str, schemas: bool) -> SourceConfigResponse:
    """配信元の設定を返す。"""
    target, _ = read_target(source, None, registry=handlers.registry)
    return get_source_config(target, store=handlers.store, schemas=schemas)


def _documents(
    handlers: Handlers, source: str, ref: str | None, values: bool
) -> DocumentListResponse:
    """リビジョンの文書の一覧を返す。"""
    target, _ = read_target(source, ref, registry=handlers.registry)
    return list_documents(target, store=handlers.store, values=values)


def _document(
    handlers: Handlers, source: str, path: str, ref: str | None, doc_id: str | None
) -> DocumentValueResponse:
    """リビジョンの文書 1 件を返す。"""
    target, _ = read_target(source, ref, registry=handlers.registry)
    return get_document(
        target, path, doc_id=doc_id, store=handlers.store, converter=handlers.converter
    )


def _decisions(handlers: Handlers, source: str) -> DecisionListResponse:
    """検討事項の一覧を返す。"""
    return DecisionListResponse(decisions=list_decisions(handlers.registry.get(source)))


def _decision(handlers: Handlers, source: str, decision_id: str) -> DecisionResponse:
    """検討事項 1 件を返す。"""
    return get_decision(handlers.registry.get(source), decision_id)


def _search(
    handlers: Handlers, source: str, ref: str | None, query: str, limit: int
) -> SearchResult:
    """検索の対象の行の文書から語を探す。"""
    target, _ = read_target(source, ref, registry=handlers.registry)
    found = [
        item
        for item in handlers.store.load(target).documents
        if target.source.table(item.kind).search
    ]
    return search_words(found, query, limit)


def _refs(handlers: Handlers, source: str, commits: int) -> RefsResponse:
    """ブランチ・タグ・最近の commit を返す。"""
    result = list_refs(handlers.registry.get(source), commits=commits)
    return RefsResponse.model_validate(dataclasses.asdict(result))


def build_read_router(handlers: Handlers) -> APIRouter:
    """読み取り API のルートを持つルーターを作る。"""
    router = APIRouter(tags=["read"])

    @router.get("/sources", name="list_sources")
    async def sources() -> SettingsSourcesResponse:
        await handlers.registry.wait_loaded()
        return SettingsSourcesResponse.from_statuses(handlers.registry.statuses())

    @router.get(
        "/sources/{source}/config", name="get_source_config", response_model=SourceConfigResponse
    )
    async def config(source: str, schemas: bool = False) -> SourceConfigResponse | Response:
        return await _run(handlers, source, "", partial(_source_config, handlers, source, schemas))

    @router.get(
        "/sources/{source}/docs", name="list_documents", response_model=DocumentListResponse
    )
    async def documents(
        source: str, ref: str | None = None, values: bool = False
    ) -> DocumentListResponse | Response:
        return await _run(handlers, source, "", partial(_documents, handlers, source, ref, values))

    @router.get(
        "/sources/{source}/docs/{path:path}",
        name="get_document",
        response_model=DocumentValueResponse,
    )
    async def document(
        source: str,
        path: str,
        ref: str | None = None,
        doc_id: Annotated[str | None, Query(alias="id")] = None,
    ) -> DocumentValueResponse | Response:
        return await _run(
            handlers, source, path, partial(_document, handlers, source, path, ref, doc_id)
        )

    @router.get(
        "/sources/{source}/decisions", name="list_decisions", response_model=DecisionListResponse
    )
    async def decisions(source: str) -> DecisionListResponse | Response:
        return await _run(handlers, source, "", partial(_decisions, handlers, source))

    @router.get(
        "/sources/{source}/decisions/{decision_id}",
        name="get_decision",
        response_model=DecisionResponse,
    )
    async def decision(source: str, decision_id: str) -> DecisionResponse | Response:
        return await _run(
            handlers, source, decision_id, partial(_decision, handlers, source, decision_id)
        )

    @router.get("/sources/{source}/search", name="search_words", response_model=SearchResult)
    async def search(
        source: str,
        q: Annotated[str, Query(min_length=1, max_length=SEARCH_QUERY_MAX)],
        ref: str | None = None,
        limit: Annotated[int, Query(ge=1, le=SEARCH_LIMIT_MAX)] = SEARCH_LIMIT_DEFAULT,
    ) -> SearchResult | Response:
        return await _run(handlers, source, "", partial(_search, handlers, source, ref, q, limit))

    @router.get("/sources/{source}/refs", name="list_refs", response_model=RefsResponse)
    async def refs(
        source: str,
        commits: Annotated[int, Query(ge=0, le=REFS_COMMITS_MAX)] = REFS_COMMITS_DEFAULT,
    ) -> RefsResponse | Response:
        return await _run(handlers, source, "", partial(_refs, handlers, source, commits))

    return router

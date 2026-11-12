"""端末の設定の取得・保存・1 行の追加のルート。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Response

from project_index.features.settings.query import load_terminal_config
from project_index.features.settings.service import add_source, save_sources
from project_index.features.settings.types import (
    SettingsSourceAddRequest,
    SettingsSourceAddResponse,
    SettingsSourceRow,
    SettingsSourcesRequest,
    SettingsSourcesResponse,
    SettingsSourcesView,
    SourceEntry,
)
from project_index.features.sources.types import SourceStatus
from project_index.server.origin import require_same_origin

if TYPE_CHECKING:
    from project_index.main import Handlers

__all__ = ["add_source", "build_settings_router", "save_sources"]


def _match_status(
    entry: SourceEntry, statuses: Sequence[SourceStatus], used: set[int]
) -> SourceStatus | None:
    """行と `config`（行に `id` があれば `id` も）が同じ、まだ重ねていない配信元の状態を探す。"""
    for status in statuses:
        if status.index in used or status.config != tuple(entry.config):
            continue
        if entry.id is not None and status.id != entry.id:
            continue
        return status
    return None


def _settings_view(handlers: Handlers) -> SettingsSourcesView:
    """端末の設定を読み直し、`sources[]` の各行に同じ `config` の配信元の状態を重ねる。"""
    terminal = load_terminal_config(handlers.terminal.file)
    statuses = handlers.registry.statuses()
    items = {
        status.index: item
        for status, item in zip(
            statuses, SettingsSourcesResponse.from_statuses(statuses).sources, strict=True
        )
    }
    rows: list[SettingsSourceRow] = []
    used: set[int] = set()
    for entry in terminal.sources:
        status = _match_status(entry, statuses, used)
        # 当たる状態が無い行は、読み直していない行
        if status is None:
            rows.append(
                SettingsSourceRow(
                    id=entry.id,
                    config=list(entry.config),
                    enabled=entry.enabled,
                    scope=entry.scope,
                    status="pending_reload",
                )
            )
            continue
        used.add(status.index)
        item = items[status.index]
        rows.append(
            SettingsSourceRow(
                id=item.id,
                config=list(entry.config),
                enabled=entry.enabled,
                scope=entry.scope,
                status=item.status,
                errors=item.errors,
                config_version=item.config_version,
            )
        )
    return SettingsSourcesView(settings_path=str(terminal.file), sources=rows)


def build_settings_router(handlers: Handlers) -> APIRouter:
    """端末の設定の取得・保存・1 行の追加のルートを持つルーターを作る。"""
    router = APIRouter(tags=["settings"])

    @router.get("/settings/sources", name="get_settings_sources")
    async def get_sources() -> SettingsSourcesView:
        await handlers.registry.wait_loaded()
        return await asyncio.to_thread(_settings_view, handlers)

    @router.put(
        "/settings/sources",
        name="put_settings_sources",
        dependencies=[Depends(require_same_origin)],
    )
    async def put_sources(body: SettingsSourcesRequest) -> SettingsSourcesResponse:
        await handlers.registry.wait_loaded()
        statuses = await asyncio.to_thread(
            save_sources,
            body.sources,
            path=handlers.terminal.file,
            reload=handlers.reload_sources,
            lock=handlers.settings_lock,
        )
        return SettingsSourcesResponse.from_statuses(statuses)

    @router.post(
        "/settings/sources",
        name="add_settings_source",
        status_code=201,
        dependencies=[Depends(require_same_origin)],
    )
    async def add_one(
        body: SettingsSourceAddRequest, response: Response
    ) -> SettingsSourceAddResponse:
        await handlers.registry.wait_loaded()
        result = await asyncio.to_thread(
            add_source,
            body.source,
            path=handlers.terminal.file,
            reload=handlers.reload_sources,
            lock=handlers.settings_lock,
        )
        # 同じ id の行があった: 追加せずに 409 で内容が同じかを返す
        if result.result == "exists":
            response.status_code = 409
        return SettingsSourceAddResponse(
            result=result.result,
            same=result.same,
            sources=SettingsSourcesResponse.from_statuses(result.statuses).sources,
        )

    return router

"""端末の設定の取得・保存と、1 行ずつの追加・変更・削除のルート。"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query, Response

from project_index.features.settings.query import (
    load_terminal_config,
    read_settings_file,
    unknown_key_warnings,
)
from project_index.features.settings.service import (
    add_source,
    delete_source,
    patch_source,
    save_sources,
)
from project_index.features.settings.types import (
    SettingsSourceAddRequest,
    SettingsSourceAddResponse,
    SettingsSourcePatchRequest,
    SettingsSourceRow,
    SettingsSourcesRequest,
    SettingsSourcesResponse,
    SettingsSourcesView,
    SettingsSourcesWriteResponse,
    SourceEntry,
)
from project_index.features.sources.types import SourceStatus
from project_index.server.origin import require_same_origin

if TYPE_CHECKING:
    from project_index.main import Handlers

__all__ = [
    "add_source",
    "build_settings_router",
    "delete_source",
    "patch_source",
    "save_sources",
]


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
    # 排他を取らずに 1 回だけ読み、内容のバージョンと行を同じ本文から求める
    text, version = read_settings_file(handlers.terminal.file)
    terminal = load_terminal_config(handlers.terminal.file, text=text)
    statuses = handlers.registry.statuses()
    items = {
        status.index: item
        for status, item in zip(
            statuses,
            SettingsSourcesResponse.from_statuses(statuses).sources,
            strict=True,
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
                    outside_read=entry.outside_read,
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
                outside_read=entry.outside_read,
            )
        )
    return SettingsSourcesView(
        settings_path=str(terminal.file),
        sources=rows,
        version=version,
        warnings=unknown_key_warnings(terminal),
    )


def build_settings_router(handlers: Handlers) -> APIRouter:
    """端末の設定の取得・保存・1 行の追加・変更・削除のルートを持つルーターを作る。"""
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
    async def put_sources(body: SettingsSourcesRequest) -> SettingsSourcesWriteResponse:
        await handlers.registry.wait_loaded()
        result = await asyncio.to_thread(
            save_sources,
            body.sources,
            expected_version=body.expected_version,
            path=handlers.terminal.file,
            reload=handlers.reload_sources,
            lock=handlers.settings_lock,
        )
        # 書き換えの後の読み直しで差し替わった端末の設定の知らないキーを警告にする
        return SettingsSourcesWriteResponse.from_result(
            result, unknown_key_warnings(handlers.terminal)
        )

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
            expected_version=body.expected_version,
            path=handlers.terminal.file,
            reload=handlers.reload_changed,
            lock=handlers.settings_lock,
        )
        # 同じ id の行があった: 追加せずに 409 で内容が同じかを返す
        if result.result == "exists":
            response.status_code = 409
        return SettingsSourceAddResponse(
            result=result.result,
            same=result.same,
            sources=SettingsSourcesResponse.from_statuses(result.statuses).sources,
            version=result.version,
            warnings=unknown_key_warnings(handlers.terminal),
        )

    @router.patch(
        "/settings/sources/{source_id}",
        name="patch_settings_source",
        dependencies=[Depends(require_same_origin)],
    )
    async def patch_one(
        source_id: str, body: SettingsSourcePatchRequest
    ) -> SettingsSourcesWriteResponse:
        await handlers.registry.wait_loaded()
        result = await asyncio.to_thread(
            patch_source,
            source_id,
            body.source,
            expected_version=body.expected_version,
            path=handlers.terminal.file,
            reload=handlers.reload_changed,
            lock=handlers.settings_lock,
        )
        # 書き換えの後の読み直しで差し替わった端末の設定の知らないキーを警告にする
        return SettingsSourcesWriteResponse.from_result(
            result, unknown_key_warnings(handlers.terminal)
        )

    @router.delete(
        "/settings/sources/{source_id}",
        name="delete_settings_source",
        dependencies=[Depends(require_same_origin)],
    )
    async def delete_one(
        source_id: str, expected_version: Annotated[str, Query(alias="expectedVersion")]
    ) -> SettingsSourcesWriteResponse:
        await handlers.registry.wait_loaded()
        result = await asyncio.to_thread(
            delete_source,
            source_id,
            expected_version=expected_version,
            path=handlers.terminal.file,
            reload=handlers.reload_changed,
            lock=handlers.settings_lock,
        )
        # 書き換えの後の読み直しで差し替わった端末の設定の知らないキーを警告にする
        return SettingsSourcesWriteResponse.from_result(
            result, unknown_key_warnings(handlers.terminal)
        )

    return router

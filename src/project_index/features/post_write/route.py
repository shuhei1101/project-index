"""`POST /_admin/post-write` のルート。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Body
from pydantic import ValidationError

from project_index.features.post_write.service import judge_post_write
from project_index.features.post_write.types import PostWriteRequest, PostWriteResponse
from project_index.shared.errors import ValidationFailedError, Violation

if TYPE_CHECKING:
    from project_index.main import Handlers


def build_post_write_router(handlers: Handlers) -> APIRouter:
    """`POST /_admin/post-write` を持つルーターを作る。"""
    router = APIRouter()

    # フックは Origin を送信しないので同一オリジンの確認は掛けない
    @router.post("/_admin/post-write", include_in_schema=False)
    async def post_post_write(
        payload: Annotated[dict[str, Any], Body()],
    ) -> PostWriteResponse:
        # 既存のハンドラーは本文の検証の失敗を 400 にするため、辞書で受けて自分で検証する
        try:
            request = PostWriteRequest.model_validate(payload)
        except ValidationError as error:
            violations = [
                Violation(path=".".join(str(part) for part in item["loc"]), rule=item["msg"])
                for item in error.errors()
            ]
            raise ValidationFailedError(
                message=f"書き込みの後の通知の入力に違反が {len(violations)} 件あります",
                violations=violations,
            ) from error
        # 配信元の一覧を読み込んでいる間: 読み込みを待たずに、通知せずに返す
        if handlers.registry.loading:
            return PostWriteResponse(notices=[], additional_context="")
        return await asyncio.to_thread(
            judge_post_write,
            request,
            sources=handlers.registry.served(),
            notified=handlers.notified,
            prompts=handlers.prompts,
        )

    return router

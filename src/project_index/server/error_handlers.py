"""例外から RFC 9457 の problem+json への変換。"""
# pyright: reportUnknownArgumentType=warning, reportUnknownVariableType=warning

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic.alias_generators import to_camel
from starlette.exceptions import HTTPException as StarletteHTTPException

from project_index.shared.errors import InvalidArgumentError, ProjectIndexError
from project_index.shared.schema_check import format_path

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)

PROBLEM_TYPE_BASE = "urn:project-index:error:"
PROBLEM_JSON = "application/problem+json"
BAD_REQUEST = 400
NOT_PARSEABLE_PARTS = ("body", "query", "path")


def _camelize(value: Any) -> Any:  # noqa: ANN401
    """入れ子のキーを camelCase にする（値が全て配列の辞書は文書の ID などの索引なのでキーを保つ）。"""
    if isinstance(value, dict):
        keep = bool(value) and all(isinstance(item, list) for item in value.values())
        return {(key if keep else to_camel(key)): _camelize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    return value


def _problem(
    name: str,
    status: int,
    detail: str,
    extra: dict[str, Any],
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """problem+json の応答を作る。"""
    body = {
        "type": f"{PROBLEM_TYPE_BASE}{name}",
        "title": name,
        "status": status,
        "detail": detail,
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def problem_of(error: ProjectIndexError, fields: dict[str, Any] | None = None) -> JSONResponse:
    """`ProjectIndexError` を problem+json の応答にする（`fields` は本文に足す値）。"""
    extra: dict[str, Any] = {
        "nextSteps": error.next_steps,
        **{to_camel(key): _camelize(value) for key, value in error.details().items()},
    }
    violations = getattr(error, "violations", None)
    if violations:
        extra["errors"] = [
            {"path": item.path, "reason": item.rule, **({"fix": item.fix} if item.fix else {})}
            for item in violations
        ]
    return _problem(error.name, error.status, error.message, {**extra, **(fields or {})})


def register_error_handlers(app: FastAPI) -> None:
    """読み取り API・端末の設定の API の例外を RFC 9457 の problem+json にするハンドラを登録する。"""

    @app.exception_handler(ProjectIndexError)
    async def project_index_error(request: Request, error: Exception) -> Response:
        assert isinstance(error, ProjectIndexError)  # noqa: S101
        return problem_of(error)

    @app.exception_handler(RequestValidationError)
    async def request_invalid(request: Request, error: Exception) -> Response:
        assert isinstance(error, RequestValidationError)  # noqa: S101
        errors = [
            {
                "path": format_path(
                    part
                    for index, part in enumerate(item["loc"])
                    if not (index == 0 and part in NOT_PARSEABLE_PARTS)
                ),
                "reason": item["msg"],
            }
            for item in error.errors()
        ]
        return _problem(
            InvalidArgumentError.__name__,
            BAD_REQUEST,
            f"引数が正しくありません: {len(errors)} 件",
            {"nextSteps": [], "errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: Exception) -> Response:
        assert isinstance(error, StarletteHTTPException)  # noqa: S101
        # 例外のヘッダー（405 の `Allow` など）は応答に載せる
        return _problem(
            "HttpError",
            error.status_code,
            str(error.detail),
            {"nextSteps": []},
            headers=error.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error: Exception) -> Response:
        logger.error(
            "要求の処理に失敗した（%s・%s・%s）",
            request.method,
            request.url.path,
            error,
            exc_info=error,
        )
        return PlainTextResponse("Internal Server Error", status_code=500)

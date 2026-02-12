from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    code: str = Field(description="エラーコード")
    message: str = Field(description="エラーメッセージ")
    details: list[dict[str, Any]] = Field(default_factory=list, description="詳細情報")


class ErrorResponse(BaseModel):
    error: ErrorDetail


@dataclass(frozen=True)
class APIError(Exception):
    status_code: int
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class BadRequestError(APIError):
    def __init__(self, message: str, *, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(400, "bad_request", message, details)


class UnauthorizedError(APIError):
    def __init__(self, message: str = "認証に失敗しました。") -> None:
        super().__init__(401, "unauthorized", message)


class ForbiddenError(APIError):
    def __init__(self, message: str = "権限がありません。") -> None:
        super().__init__(403, "forbidden", message)


class NotFoundError(APIError):
    def __init__(self, message: str) -> None:
        super().__init__(404, "not_found", message)


class ConflictError(APIError):
    def __init__(self, message: str) -> None:
        super().__init__(409, "conflict", message)


class UnprocessableEntityError(APIError):
    def __init__(self, message: str, *, details: list[dict[str, Any]] | None = None) -> None:
        super().__init__(422, "validation_error", message, details)


class TooManyRequestsError(APIError):
    def __init__(self, message: str) -> None:
        super().__init__(429, "limit_exceeded", message)


class InternalServerError(APIError):
    def __init__(self, message: str = "サーバー内部でエラーが発生しました。") -> None:
        super().__init__(500, "internal_error", message)


def build_error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _handle_api_error(_: Request, exc: APIError) -> JSONResponse:
        return build_error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "loc": list(error.get("loc", ())),
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        return build_error_response(
            status_code=422,
            code="validation_error",
            message="入力内容が不正です。",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        status_code = exc.status_code
        code_map = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            422: "validation_error",
            429: "limit_exceeded",
            500: "internal_error",
        }
        code = code_map.get(status_code, "http_error")
        message = str(exc.detail) if exc.detail else "HTTPエラーが発生しました。"
        return build_error_response(status_code=status_code, code=code, message=message)

    @app.exception_handler(Exception)
    async def _handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception", exc_info=exc)
        return build_error_response(
            status_code=500,
            code="internal_error",
            message="サーバー内部でエラーが発生しました。",
        )

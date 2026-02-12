from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from starlette.responses import Response

from kabu_per_bot.api.auth import authenticate_request, is_protected_path
from kabu_per_bot.api.errors import APIError, build_error_response


def install_auth_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _firebase_auth_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method != "OPTIONS" and is_protected_path(request.url.path):
            try:
                request.state.auth = authenticate_request(request)
            except APIError as exc:
                return build_error_response(
                    status_code=exc.status_code,
                    code=exc.code,
                    message=exc.message,
                    details=exc.details,
                )
        return await call_next(request)

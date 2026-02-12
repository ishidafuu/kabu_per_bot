from __future__ import annotations

from typing import Any

from kabu_per_bot.api.errors import ErrorResponse

ERROR_RESPONSES: dict[int, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "パラメータ不正"},
    401: {"model": ErrorResponse, "description": "未認証"},
    403: {"model": ErrorResponse, "description": "認可エラー"},
    404: {"model": ErrorResponse, "description": "リソースなし"},
    409: {"model": ErrorResponse, "description": "重複"},
    422: {"model": ErrorResponse, "description": "入力バリデーション不正"},
    429: {"model": ErrorResponse, "description": "件数上限超過"},
    500: {"model": ErrorResponse, "description": "想定外エラー"},
}


def error_responses(*codes: int) -> dict[int, dict[str, Any]]:
    responses: dict[int, dict[str, Any]] = {}
    for code in codes:
        if code in ERROR_RESPONSES:
            responses[code] = ERROR_RESPONSES[code]
    return responses

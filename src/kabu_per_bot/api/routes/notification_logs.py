from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from kabu_per_bot.api.dependencies import NotificationLogReader, get_notification_log_repository
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import NotificationLogItemResponse, NotificationLogListResponse

router = APIRouter(
    prefix="/notifications",
    tags=["notification-logs"],
)


@router.get(
    "/logs",
    response_model=NotificationLogListResponse,
    responses=error_responses(401, 403, 422, 500),
)
def list_notification_logs(
    ticker: str | None = Query(default=None, pattern=r"^\d{4}:[Tt][Ss][Ee]$"),
    category: str | None = Query(default=None, max_length=64),
    strong_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: NotificationLogReader = Depends(get_notification_log_repository),
) -> NotificationLogListResponse:
    is_strong_filter = True if strong_only else None
    rows = repository.list_timeline(
        ticker=ticker,
        category=category,
        is_strong=is_strong_filter,
        limit=limit,
        offset=offset,
    )
    total = repository.count_timeline(
        ticker=ticker,
        category=category,
        is_strong=is_strong_filter,
    )
    return NotificationLogListResponse(
        items=[NotificationLogItemResponse.from_domain(row) for row in rows],
        total=total,
    )

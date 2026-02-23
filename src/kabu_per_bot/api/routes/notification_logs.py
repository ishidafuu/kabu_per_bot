from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from kabu_per_bot.api.dependencies import NotificationLogReader, get_notification_log_repository, get_watchlist_service
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import NotificationLogItemResponse, NotificationLogListResponse
from kabu_per_bot.watchlist import WatchPriority, WatchlistService

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
    priority: WatchPriority | None = Query(default=None),
    category: str | None = Query(default=None, max_length=64),
    strong_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: NotificationLogReader = Depends(get_notification_log_repository),
    watchlist_service: WatchlistService = Depends(get_watchlist_service),
) -> NotificationLogListResponse:
    is_strong_filter = True if strong_only else None
    if priority is None:
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
    else:
        watchlist_priorities = {item.ticker: item.priority for item in watchlist_service.list_items()}
        all_rows = repository.list_timeline(
            ticker=ticker,
            category=category,
            is_strong=is_strong_filter,
            limit=None,
            offset=0,
        )
        filtered = [row for row in all_rows if watchlist_priorities.get(row.ticker) == priority]
        total = len(filtered)
        rows = filtered[offset : offset + limit]

    return NotificationLogListResponse(
        items=[NotificationLogItemResponse.from_domain(row) for row in rows],
        total=total,
    )

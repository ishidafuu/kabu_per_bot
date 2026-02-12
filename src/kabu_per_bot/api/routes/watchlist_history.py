from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from kabu_per_bot.api.dependencies import WatchlistHistoryReader, get_watchlist_history_repository
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import WatchlistHistoryItemResponse, WatchlistHistoryListResponse

router = APIRouter(
    prefix="/watchlist",
    tags=["watchlist-history"],
)


@router.get(
    "/history",
    response_model=WatchlistHistoryListResponse,
    responses=error_responses(401, 403, 422, 500),
)
def list_watchlist_history(
    ticker: str | None = Query(default=None, pattern=r"^\d{4}:[A-Za-z]+$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: WatchlistHistoryReader = Depends(get_watchlist_history_repository),
) -> WatchlistHistoryListResponse:
    rows = repository.list_timeline(ticker=ticker, limit=limit, offset=offset)
    total = repository.count_timeline(ticker=ticker)
    return WatchlistHistoryListResponse(
        items=[WatchlistHistoryItemResponse.from_domain(row) for row in rows],
        total=total,
    )

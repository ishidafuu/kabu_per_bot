from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status

from kabu_per_bot.api.dependencies import get_watchlist_service
from kabu_per_bot.api.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    TooManyRequestsError,
    UnprocessableEntityError,
)
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import (
    WatchlistCreateRequest,
    WatchlistItemResponse,
    WatchlistListResponse,
    WatchlistUpdateRequest,
)
from kabu_per_bot.watchlist import (
    WatchlistAlreadyExistsError,
    WatchlistError,
    WatchlistLimitExceededError,
    WatchlistNotFoundError,
    WatchlistService,
)

router = APIRouter(
    prefix="/watchlist",
    tags=["watchlist"],
)


@router.get(
    "",
    response_model=WatchlistListResponse,
    responses=error_responses(400, 401, 403, 422, 500),
)
def list_watchlist(
    q: str | None = Query(default=None, description="ticker/name の部分一致検索"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistListResponse:
    items = service.list_items()

    if q:
        needle = q.strip().lower()
        items = [item for item in items if needle in item.ticker.lower() or needle in item.name.lower()]

    total = len(items)
    paged_items = items[offset : offset + limit]
    return WatchlistListResponse(items=[WatchlistItemResponse.from_domain(item) for item in paged_items], total=total)


@router.get(
    "/{ticker}",
    response_model=WatchlistItemResponse,
    responses=error_responses(401, 403, 404, 422, 500),
)
def get_watchlist_item(
    ticker: str,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistItemResponse:
    try:
        item = service.get_item(ticker)
    except WatchlistNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except (ValueError, WatchlistError) as exc:
        raise UnprocessableEntityError(str(exc)) from exc
    return WatchlistItemResponse.from_domain(item)


@router.post(
    "",
    response_model=WatchlistItemResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 422, 429, 500),
)
def create_watchlist_item(
    payload: WatchlistCreateRequest,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistItemResponse:
    try:
        created = service.add_item(
            ticker=payload.ticker,
            name=payload.name,
            metric_type=payload.metric_type,
            notify_channel=payload.notify_channel,
            notify_timing=payload.notify_timing,
            ai_enabled=payload.ai_enabled,
            is_active=payload.is_active,
        )
    except WatchlistAlreadyExistsError as exc:
        raise ConflictError(str(exc)) from exc
    except WatchlistLimitExceededError as exc:
        raise TooManyRequestsError(str(exc)) from exc
    except (ValueError, WatchlistError) as exc:
        raise UnprocessableEntityError(str(exc)) from exc
    return WatchlistItemResponse.from_domain(created)


@router.patch(
    "/{ticker}",
    response_model=WatchlistItemResponse,
    responses=error_responses(400, 401, 403, 404, 422, 500),
)
def update_watchlist_item(
    ticker: str,
    payload: WatchlistUpdateRequest,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistItemResponse:
    if not payload.has_updates():
        raise BadRequestError("更新対象のフィールドを1つ以上指定してください。")

    try:
        updated = service.update_item(
            ticker,
            name=payload.name,
            metric_type=payload.metric_type,
            notify_channel=payload.notify_channel,
            notify_timing=payload.notify_timing,
            ai_enabled=payload.ai_enabled,
            is_active=payload.is_active,
        )
    except WatchlistNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except (ValueError, WatchlistError) as exc:
        raise UnprocessableEntityError(str(exc)) from exc
    return WatchlistItemResponse.from_domain(updated)


@router.delete(
    "/{ticker}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 422, 500),
)
def delete_watchlist_item(
    ticker: str,
    service: WatchlistService = Depends(get_watchlist_service),
) -> Response:
    try:
        service.delete_item(ticker)
    except WatchlistNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except (ValueError, WatchlistError) as exc:
        raise UnprocessableEntityError(str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)

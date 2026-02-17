from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response, status

from kabu_per_bot.api.dependencies import get_watchlist_service
from kabu_per_bot.api.errors import (
    BadRequestError,
    ConflictError,
    InternalServerError,
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
    MetricType,
    WatchlistAlreadyExistsError,
    WatchlistError,
    WatchlistLimitExceededError,
    WatchlistNotFoundError,
    WatchlistItem,
    WatchlistService,
)

router = APIRouter(
    prefix="/watchlist",
    tags=["watchlist"],
)

JST = ZoneInfo("Asia/Tokyo")


@contextmanager
def _translate_watchlist_error() -> Iterator[None]:
    try:
        yield
    except WatchlistNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except WatchlistAlreadyExistsError as exc:
        raise ConflictError(str(exc)) from exc
    except WatchlistLimitExceededError as exc:
        raise TooManyRequestsError(str(exc)) from exc
    except (ValueError, WatchlistError) as exc:
        raise UnprocessableEntityError(str(exc)) from exc


@router.get(
    "",
    response_model=WatchlistListResponse,
    responses=error_responses(400, 401, 403, 422, 500),
)
def list_watchlist(
    request: Request,
    q: str | None = Query(default=None, description="ticker/name の部分一致検索"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_status: bool = Query(default=False, description="最新指標/判定/次回決算を含める"),
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistListResponse:
    items = service.list_items()

    if q:
        needle = q.strip().lower()
        items = [item for item in items if needle in item.ticker.lower() or needle in item.name.lower()]

    total = len(items)
    paged_items = items[offset : offset + limit]
    if not include_status:
        return WatchlistListResponse(items=[WatchlistItemResponse.from_domain(item) for item in paged_items], total=total)

    daily_metrics_repo = _resolve_status_dependency(
        request=request,
        value_key="daily_metrics_repository",
        factory_key="daily_metrics_repository_factory",
    )
    metric_medians_repo = _resolve_status_dependency(
        request=request,
        value_key="metric_medians_repository",
        factory_key="metric_medians_repository_factory",
    )
    signal_state_repo = _resolve_status_dependency(
        request=request,
        value_key="signal_state_repository",
        factory_key="signal_state_repository_factory",
    )
    earnings_calendar_repo = _resolve_status_dependency(
        request=request,
        value_key="earnings_calendar_repository",
        factory_key="earnings_calendar_repository_factory",
    )
    today_jst = datetime.now(JST).date().isoformat()
    response_items = [
        _build_watchlist_item_response(
            item=item,
            daily_metrics_repo=daily_metrics_repo,
            metric_medians_repo=metric_medians_repo,
            signal_state_repo=signal_state_repo,
            earnings_calendar_repo=earnings_calendar_repo,
            today_jst=today_jst,
        )
        for item in paged_items
    ]
    return WatchlistListResponse(items=response_items, total=total)


@router.get(
    "/{ticker}",
    response_model=WatchlistItemResponse,
    responses=error_responses(401, 403, 404, 422, 500),
)
def get_watchlist_item(
    ticker: str,
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistItemResponse:
    with _translate_watchlist_error():
        item = service.get_item(ticker)
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
    with _translate_watchlist_error():
        created = service.add_item(
            ticker=payload.ticker,
            name=payload.name,
            metric_type=payload.metric_type,
            notify_channel=payload.notify_channel,
            notify_timing=payload.notify_timing,
            ai_enabled=payload.ai_enabled,
            is_active=payload.is_active,
            ir_urls=payload.ir_urls,
            x_official_account=payload.x_official_account,
            x_executive_accounts=[row.model_dump() for row in payload.x_executive_accounts],
            reason=payload.reason,
        )
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

    with _translate_watchlist_error():
        updated = service.update_item(
            ticker,
            name=payload.name,
            metric_type=payload.metric_type,
            notify_channel=payload.notify_channel,
            notify_timing=payload.notify_timing,
            ai_enabled=payload.ai_enabled,
            is_active=payload.is_active,
            ir_urls=payload.ir_urls,
            x_official_account=payload.x_official_account,
            x_executive_accounts=(
                [row.model_dump() for row in payload.x_executive_accounts]
                if payload.x_executive_accounts is not None
                else None
            ),
        )
    return WatchlistItemResponse.from_domain(updated)


@router.delete(
    "/{ticker}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 422, 500),
)
def delete_watchlist_item(
    ticker: str,
    reason: str | None = Query(default=None, max_length=200),
    service: WatchlistService = Depends(get_watchlist_service),
) -> Response:
    with _translate_watchlist_error():
        service.delete_item(ticker, reason=reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _resolve_status_dependency(
    *,
    request: Request,
    value_key: str,
    factory_key: str,
):
    dependency = getattr(request.app.state, value_key, None)
    if dependency is not None:
        return dependency

    factory = getattr(request.app.state, factory_key, None)
    if factory is None:
        raise InternalServerError(f"{value_key} の依存解決に失敗しました。")
    try:
        dependency = factory()
    except Exception as exc:
        raise InternalServerError(f"{value_key} の初期化に失敗しました。") from exc
    setattr(request.app.state, value_key, dependency)
    return dependency


def _build_watchlist_item_response(
    *,
    item: WatchlistItem,
    daily_metrics_repo,
    metric_medians_repo,
    signal_state_repo,
    earnings_calendar_repo,
    today_jst: str,
) -> WatchlistItemResponse:
    current_metric_value: float | None = None
    median_1w: float | None = None
    median_3m: float | None = None
    median_1y: float | None = None
    signal_category: str | None = None
    signal_combo: str | None = None
    signal_is_strong: bool | None = None
    signal_streak_days: int | None = None
    next_earnings_date: str | None = None
    next_earnings_time: str | None = None

    if daily_metrics_repo is not None:
        metrics = daily_metrics_repo.list_recent(item.ticker, limit=1)
        if metrics:
            latest = metrics[0]
            current_metric_value = latest.per_value if item.metric_type is MetricType.PER else latest.psr_value

    if metric_medians_repo is not None:
        medians_rows = metric_medians_repo.list_recent(item.ticker, limit=1)
        if medians_rows:
            medians = medians_rows[0]
            median_1w = medians.median_1w
            median_3m = medians.median_3m
            median_1y = medians.median_1y

    if signal_state_repo is not None:
        state = signal_state_repo.get_latest(item.ticker)
        if state is not None:
            signal_category = state.category
            signal_combo = state.combo
            signal_is_strong = state.is_strong
            signal_streak_days = state.streak_days

    if earnings_calendar_repo is not None:
        future_rows = [row for row in earnings_calendar_repo.list_by_ticker(item.ticker) if row.earnings_date >= today_jst]
        if future_rows:
            future_rows.sort(key=lambda row: (row.earnings_date, row.earnings_time or "99:99"))
            target = future_rows[0]
            next_earnings_date = target.earnings_date
            next_earnings_time = target.earnings_time

    return WatchlistItemResponse.from_domain(
        item,
        current_metric_value=current_metric_value,
        median_1w=median_1w,
        median_3m=median_3m,
        median_1y=median_1y,
        signal_category=signal_category,
        signal_combo=signal_combo,
        signal_is_strong=signal_is_strong,
        signal_streak_days=signal_streak_days,
        next_earnings_date=next_earnings_date,
        next_earnings_time=next_earnings_time,
    )

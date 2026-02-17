from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response, status

from kabu_per_bot.earnings import EarningsCalendarEntry
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
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.signal import SignalState
from kabu_per_bot.watchlist import (
    MetricType,
    NotifyChannel,
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
    target_tickers = [item.ticker for item in paged_items]
    latest_metrics_by_ticker = _load_latest_metrics_by_ticker(daily_metrics_repo, target_tickers)
    latest_medians_by_ticker = _load_latest_medians_by_ticker(metric_medians_repo, target_tickers)
    latest_states_by_ticker = _load_latest_signal_states_by_ticker(signal_state_repo, target_tickers)
    next_earnings_by_ticker = _load_next_earnings_by_ticker(earnings_calendar_repo, target_tickers, from_date=today_jst)
    response_items = [
        _build_watchlist_item_response(
            item=item,
            latest_metric=latest_metrics_by_ticker.get(item.ticker),
            latest_medians=latest_medians_by_ticker.get(item.ticker),
            latest_signal_state=latest_states_by_ticker.get(item.ticker),
            next_earnings=next_earnings_by_ticker.get(item.ticker),
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
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=payload.notify_timing,
            always_notify_enabled=payload.always_notify_enabled,
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
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=payload.notify_timing,
            always_notify_enabled=payload.always_notify_enabled,
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
    latest_metric: DailyMetric | None,
    latest_medians: MetricMedians | None,
    latest_signal_state: SignalState | None,
    next_earnings: EarningsCalendarEntry | None,
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

    if latest_metric is not None:
        current_metric_value = latest_metric.per_value if item.metric_type is MetricType.PER else latest_metric.psr_value

    if latest_medians is not None:
        median_1w = latest_medians.median_1w
        median_3m = latest_medians.median_3m
        median_1y = latest_medians.median_1y

    if latest_signal_state is not None:
        signal_category = latest_signal_state.category
        signal_combo = latest_signal_state.combo
        signal_is_strong = latest_signal_state.is_strong
        signal_streak_days = latest_signal_state.streak_days

    if next_earnings is not None:
        next_earnings_date = next_earnings.earnings_date
        next_earnings_time = next_earnings.earnings_time

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


def _load_latest_metrics_by_ticker(repository: Any, tickers: list[str]) -> dict[str, DailyMetric]:
    bulk_loader = getattr(repository, "list_latest_by_tickers", None)
    if callable(bulk_loader):
        return _normalize_map_keys(_call_repository(bulk_loader, tickers=tickers))

    latest_by_ticker: dict[str, DailyMetric] = {}
    for ticker in tickers:
        rows = _call_repository(repository.list_recent, ticker=ticker, limit=1)
        if rows:
            latest_by_ticker[ticker] = rows[0]
    return latest_by_ticker


def _load_latest_medians_by_ticker(repository: Any, tickers: list[str]) -> dict[str, MetricMedians]:
    bulk_loader = getattr(repository, "list_latest_by_tickers", None)
    if callable(bulk_loader):
        return _normalize_map_keys(_call_repository(bulk_loader, tickers=tickers))

    latest_by_ticker: dict[str, MetricMedians] = {}
    for ticker in tickers:
        rows = _call_repository(repository.list_recent, ticker=ticker, limit=1)
        if rows:
            latest_by_ticker[ticker] = rows[0]
    return latest_by_ticker


def _load_latest_signal_states_by_ticker(repository: Any, tickers: list[str]) -> dict[str, SignalState]:
    bulk_loader = getattr(repository, "get_latest_by_tickers", None)
    if callable(bulk_loader):
        return _normalize_map_keys(_call_repository(bulk_loader, tickers=tickers))

    latest_by_ticker: dict[str, SignalState] = {}
    for ticker in tickers:
        state = _call_repository(repository.get_latest, ticker=ticker)
        if state is not None:
            latest_by_ticker[ticker] = state
    return latest_by_ticker


def _load_next_earnings_by_ticker(
    repository: Any,
    tickers: list[str],
    *,
    from_date: str,
) -> dict[str, EarningsCalendarEntry]:
    bulk_loader = getattr(repository, "list_next_by_tickers", None)
    if callable(bulk_loader):
        return _normalize_map_keys(_call_repository(bulk_loader, tickers=tickers, from_date=from_date))

    next_by_ticker: dict[str, EarningsCalendarEntry] = {}
    for ticker in tickers:
        rows = _call_repository(repository.list_by_ticker, ticker=ticker)
        future_rows = [row for row in rows if row.earnings_date >= from_date]
        if not future_rows:
            continue
        future_rows.sort(key=lambda row: (row.earnings_date, row.earnings_time or "99:99"))
        next_by_ticker[ticker] = future_rows[0]
    return next_by_ticker


def _call_repository(callable_obj, **kwargs):
    try:
        return callable_obj(**kwargs)
    except Exception as exc:
        raise InternalServerError("watchlist詳細情報の取得に失敗しました。") from exc


def _normalize_map_keys(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise InternalServerError("watchlist詳細情報の取得結果が不正です。")
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        normalized[str(key).strip().upper()] = value
    return normalized

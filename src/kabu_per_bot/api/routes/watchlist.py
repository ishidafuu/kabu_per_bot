from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import logging
import os
import threading
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, Response, status

from kabu_per_bot.earnings import EarningsCalendarEntry
from kabu_per_bot.api.dependencies import (
    AdminOpsReader,
    NotificationLogReader,
    TechnicalAlertRulesReader,
    TechnicalIndicatorsReader,
    WatchlistHistoryReader,
    create_firestore_client,
    get_admin_ops_service,
    get_notification_log_repository,
    get_technical_alert_rules_repository,
    get_technical_indicators_repository,
    get_ir_url_candidate_service,
    get_watchlist_history_repository,
    get_watchlist_service,
    require_admin_user,
)
from kabu_per_bot.backfill_service import (
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    backfill_ticker_from_jquants,
    refresh_latest_medians_and_signal,
    resolve_incremental_from_date,
    upsert_latest_snapshot_metric,
)
from kabu_per_bot.jquants_v2 import JQuantsV2Client
from kabu_per_bot.market_data import create_default_market_data_source
from kabu_per_bot.notification import format_signal_status_message
from kabu_per_bot.api.errors import (
    BadRequestError,
    ConflictError,
    InternalServerError,
    NotFoundError,
    TooManyRequestsError,
    UnprocessableEntityError,
)
from kabu_per_bot.admin_ops import AdminOpsConfigError, AdminOpsConflictError, AdminOpsNotFoundError, TickerScopedRunRequest
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import (
    TechnicalInitialFetchResponse,
    IrUrlCandidateListResponse,
    IrUrlCandidateResponse,
    IrUrlCandidateSuggestRequest,
    NotificationLogItemResponse,
    NotificationLogListResponse,
    TechnicalAlertRuleCreateRequest,
    TechnicalAlertRuleListResponse,
    TechnicalAlertRuleResponse,
    TechnicalAlertRuleUpdateRequest,
    TechnicalIndicatorSnapshotResponse,
    WatchlistCreateRequest,
    WatchlistDetailResponse,
    WatchlistDetailSummaryResponse,
    WatchlistHistoryItemResponse,
    WatchlistHistoryListResponse,
    WatchlistItemResponse,
    WatchlistListResponse,
    WatchlistUpdateRequest,
)
from kabu_per_bot.ir_url_candidates import IrUrlSuggestionError
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.runtime_settings import resolve_runtime_settings
from kabu_per_bot.settings import load_settings
from kabu_per_bot.signal import NotificationLogEntry, SignalState, evaluate_cooldown
from kabu_per_bot.storage.firestore_daily_metrics_repository import FirestoreDailyMetricsRepository
from kabu_per_bot.storage.firestore_metric_medians_repository import FirestoreMetricMediansRepository
from kabu_per_bot.storage.firestore_signal_state_repository import FirestoreSignalStateRepository
from kabu_per_bot.technical import TechnicalAlertRule, TechnicalIndicatorsDaily
from kabu_per_bot.watchlist import (
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchPriority,
    WatchlistAlreadyExistsError,
    WatchlistError,
    WatchlistLimitExceededError,
    WatchlistNotFoundError,
    WatchlistItem,
    WatchlistService,
)

LOGGER = logging.getLogger(__name__)

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
    priority: WatchPriority | None = Query(default=None, description="優先度で絞り込み"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_status: bool = Query(default=False, description="最新指標/判定/次回決算/決算まで日数を含める"),
    service: WatchlistService = Depends(get_watchlist_service),
) -> WatchlistListResponse:
    items = service.list_items()

    if q:
        needle = q.strip().lower()
        items = [item for item in items if needle in item.ticker.lower() or needle in item.name.lower()]
    if priority is not None:
        items = [item for item in items if item.priority == priority]

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
    recent_notifications_by_ticker = _load_recent_notifications_by_ticker_optional(request=request, tickers=target_tickers)
    now_iso = datetime.now(timezone.utc).isoformat()
    cooldown_hours = _resolve_cooldown_hours(request=request)
    response_items = [
        _build_watchlist_item_response(
            item=item,
            latest_metric=latest_metrics_by_ticker.get(item.ticker),
            latest_medians=latest_medians_by_ticker.get(item.ticker),
            latest_signal_state=latest_states_by_ticker.get(item.ticker),
            notification_skip_reason=_resolve_notification_skip_reason(
                item=item,
                latest_metric=latest_metrics_by_ticker.get(item.ticker),
                latest_medians=latest_medians_by_ticker.get(item.ticker),
                latest_signal_state=latest_states_by_ticker.get(item.ticker),
                recent_notifications=recent_notifications_by_ticker.get(item.ticker, []),
                cooldown_hours=cooldown_hours,
                now_iso=now_iso,
            ),
            next_earnings=next_earnings_by_ticker.get(item.ticker),
        )
        for item in paged_items
    ]
    return WatchlistListResponse(items=response_items, total=total)


@router.post(
    "/ir-url-candidates",
    response_model=IrUrlCandidateListResponse,
    responses=error_responses(401, 403, 422, 500),
)
def suggest_ir_url_candidates(
    payload: IrUrlCandidateSuggestRequest,
    service=Depends(get_ir_url_candidate_service),
) -> IrUrlCandidateListResponse:
    try:
        candidates = service.suggest_candidates(
            ticker=payload.ticker,
            company_name=payload.company_name,
            max_candidates=payload.max_candidates,
        )
    except IrUrlSuggestionError as exc:
        raise InternalServerError(f"IR候補URLの生成に失敗しました: {exc}") from exc
    except ValueError as exc:
        raise UnprocessableEntityError(str(exc)) from exc

    rows = [
        IrUrlCandidateResponse(
            url=row.url,
            title=row.title,
            reason=row.reason,
            confidence=row.confidence,
            validation_status=row.validation_status,
            score=row.score,
            http_status=row.http_status,
            content_type=row.content_type,
        )
        for row in candidates
    ]
    return IrUrlCandidateListResponse(items=rows, total=len(rows))


@router.get(
    "/{ticker}/detail",
    response_model=WatchlistDetailResponse,
    responses=error_responses(401, 403, 404, 422, 500),
)
def get_watchlist_item_detail(
    request: Request,
    ticker: str,
    category: str | None = Query(default=None, max_length=64, description="通知カテゴリで絞り込み"),
    strong_only: bool = Query(default=False, description="強通知のみを表示"),
    sent_at_from: str | None = Query(default=None, description="通知時刻の開始ISO8601"),
    sent_at_to: str | None = Query(default=None, description="通知時刻の終了ISO8601"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    history_limit: int = Query(default=20, ge=1, le=100),
    history_offset: int = Query(default=0, ge=0),
    service: WatchlistService = Depends(get_watchlist_service),
    notification_log_repo: NotificationLogReader = Depends(get_notification_log_repository),
    watchlist_history_repo: WatchlistHistoryReader = Depends(get_watchlist_history_repository),
) -> WatchlistDetailResponse:
    with _translate_watchlist_error():
        item = service.get_item(ticker)

    item_response = _build_watchlist_item_response_with_optional_status(request=request, item=item)

    now_jst = datetime.now(JST)
    sent_at_7d_from = (now_jst - timedelta(days=7)).astimezone(timezone.utc).isoformat()
    sent_at_30d_from = (now_jst - timedelta(days=30)).astimezone(timezone.utc).isoformat()
    strong_filter = True if strong_only else None

    latest_rows = _call_repository(
        notification_log_repo.list_timeline,
        ticker=item.ticker,
        limit=1,
        offset=0,
    )
    latest = latest_rows[0] if latest_rows else None

    summary = WatchlistDetailSummaryResponse(
        last_notification_at=latest.sent_at if latest is not None else None,
        last_notification_category=latest.category if latest is not None else None,
        notification_count_7d=_call_repository(
            notification_log_repo.count_timeline,
            ticker=item.ticker,
            sent_at_from=sent_at_7d_from,
        ),
        strong_notification_count_30d=_call_repository(
            notification_log_repo.count_timeline,
            ticker=item.ticker,
            is_strong=True,
            sent_at_from=sent_at_30d_from,
        ),
        data_unknown_count_30d=_call_repository(
            notification_log_repo.count_timeline,
            ticker=item.ticker,
            category="データ不明",
            sent_at_from=sent_at_30d_from,
        ),
    )

    notification_rows = _call_repository(
        notification_log_repo.list_timeline,
        ticker=item.ticker,
        category=category,
        is_strong=strong_filter,
        sent_at_from=sent_at_from,
        sent_at_to=sent_at_to,
        limit=limit,
        offset=offset,
    )
    notification_total = _call_repository(
        notification_log_repo.count_timeline,
        ticker=item.ticker,
        category=category,
        is_strong=strong_filter,
        sent_at_from=sent_at_from,
        sent_at_to=sent_at_to,
    )
    history_rows = _call_repository(
        watchlist_history_repo.list_timeline,
        ticker=item.ticker,
        limit=history_limit,
        offset=history_offset,
    )
    history_total = _call_repository(watchlist_history_repo.count_timeline, ticker=item.ticker)
    technical_rules = _load_technical_alert_rules_optional(request=request, ticker=item.ticker)
    latest_technical = _load_latest_technical_optional(request=request, ticker=item.ticker)
    technical_alert_history_rows = _call_repository(
        notification_log_repo.list_timeline,
        ticker=item.ticker,
        category="技術アラート",
        limit=10,
        offset=0,
    )
    technical_alert_history_total = _call_repository(
        notification_log_repo.count_timeline,
        ticker=item.ticker,
        category="技術アラート",
    )

    return WatchlistDetailResponse(
        item=item_response,
        summary=summary,
        notifications=NotificationLogListResponse(
            items=[NotificationLogItemResponse.from_domain(row) for row in notification_rows],
            total=notification_total,
        ),
        history=WatchlistHistoryListResponse(
            items=[WatchlistHistoryItemResponse.from_domain(row) for row in history_rows],
            total=history_total,
        ),
        technical_rules=TechnicalAlertRuleListResponse(
            items=[TechnicalAlertRuleResponse.from_domain(row) for row in technical_rules],
            total=len(technical_rules),
        ),
        latest_technical=(
            TechnicalIndicatorSnapshotResponse.from_domain(latest_technical)
            if latest_technical is not None
            else None
        ),
        technical_alert_history=NotificationLogListResponse(
            items=[NotificationLogItemResponse.from_domain(row) for row in technical_alert_history_rows],
            total=technical_alert_history_total,
        ),
    )


@router.get(
    "/{ticker}/technical-alert-rules",
    response_model=TechnicalAlertRuleListResponse,
    responses=error_responses(401, 403, 404, 422, 500),
)
def list_technical_alert_rules(
    ticker: str,
    service: WatchlistService = Depends(get_watchlist_service),
    technical_alert_rules_repo: TechnicalAlertRulesReader = Depends(get_technical_alert_rules_repository),
) -> TechnicalAlertRuleListResponse:
    with _translate_watchlist_error():
        item = service.get_item(ticker)
    rows = technical_alert_rules_repo.list_recent(item.ticker, limit=100)
    return TechnicalAlertRuleListResponse(
        items=[TechnicalAlertRuleResponse.from_domain(row) for row in rows],
        total=len(rows),
    )


@router.post(
    "/{ticker}/technical-alert-rules",
    response_model=TechnicalAlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 422, 500),
)
def create_technical_alert_rule(
    ticker: str,
    payload: TechnicalAlertRuleCreateRequest,
    service: WatchlistService = Depends(get_watchlist_service),
    technical_alert_rules_repo: TechnicalAlertRulesReader = Depends(get_technical_alert_rules_repository),
) -> TechnicalAlertRuleResponse:
    with _translate_watchlist_error():
        item = service.get_item(ticker)
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        rule = TechnicalAlertRule.create(
            ticker=item.ticker,
            rule_name=payload.rule_name,
            field_key=payload.field_key,
            operator=payload.operator,
            threshold_value=payload.threshold_value,
            threshold_upper=payload.threshold_upper,
            is_active=payload.is_active,
            note=payload.note,
            created_at=now_iso,
            updated_at=now_iso,
        )
    except ValueError as exc:
        raise UnprocessableEntityError(str(exc)) from exc
    technical_alert_rules_repo.upsert(rule)
    return TechnicalAlertRuleResponse.from_domain(rule)


@router.patch(
    "/{ticker}/technical-alert-rules/{rule_id}",
    response_model=TechnicalAlertRuleResponse,
    responses=error_responses(401, 403, 404, 422, 500),
)
def update_technical_alert_rule(
    ticker: str,
    rule_id: str,
    payload: TechnicalAlertRuleUpdateRequest,
    service: WatchlistService = Depends(get_watchlist_service),
    technical_alert_rules_repo: TechnicalAlertRulesReader = Depends(get_technical_alert_rules_repository),
) -> TechnicalAlertRuleResponse:
    with _translate_watchlist_error():
        item = service.get_item(ticker)
    existing = technical_alert_rules_repo.get(item.ticker, rule_id)
    if existing is None:
        raise NotFoundError("technical alert rule が見つかりません。")
    try:
        updated = TechnicalAlertRule(
            rule_id=existing.rule_id,
            ticker=item.ticker,
            rule_name=payload.rule_name if payload.rule_name is not None else existing.rule_name,
            field_key=payload.field_key if payload.field_key is not None else existing.field_key,
            operator=payload.operator if payload.operator is not None else existing.operator,
            threshold_value=payload.threshold_value if payload.threshold_value is not None else existing.threshold_value,
            threshold_upper=payload.threshold_upper if payload.threshold_upper is not None else existing.threshold_upper,
            is_active=payload.is_active if payload.is_active is not None else existing.is_active,
            note=payload.note if payload.note is not None else existing.note,
            created_at=existing.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
    except ValueError as exc:
        raise UnprocessableEntityError(str(exc)) from exc
    technical_alert_rules_repo.upsert(updated)
    return TechnicalAlertRuleResponse.from_domain(updated)


@router.post(
    "/{ticker}/technical-initial-fetch",
    response_model=TechnicalInitialFetchResponse,
    responses=error_responses(401, 403, 404, 409, 422, 500),
    dependencies=[Depends(require_admin_user)],
)
def trigger_technical_initial_fetch(
    ticker: str,
    service: WatchlistService = Depends(get_watchlist_service),
    admin_ops_service: AdminOpsReader = Depends(get_admin_ops_service),
) -> TechnicalInitialFetchResponse:
    with _translate_watchlist_error():
        item = service.get_item(ticker)
    try:
        execution = admin_ops_service.run_job(
            job_key="technical_full_refresh",
            ticker_scope=TickerScopedRunRequest(tickers=(item.ticker,)),
        )
    except AdminOpsNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except AdminOpsConflictError as exc:
        raise ConflictError(str(exc)) from exc
    except (AdminOpsConfigError, ValueError) as exc:
        raise UnprocessableEntityError(str(exc)) from exc
    except Exception as exc:
        raise InternalServerError(f"技術過去データ取得ジョブの起動に失敗しました: {exc}") from exc
    return TechnicalInitialFetchResponse(
        execution_name=execution.execution_name,
        status=execution.status,
        job_key=execution.job_key,
        job_label=execution.job_label,
        message=execution.message,
    )


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
    request: Request,
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
            priority=payload.priority,
            always_notify_enabled=payload.always_notify_enabled,
            ai_enabled=True,
            is_active=payload.is_active,
            evaluation_enabled=payload.evaluation_enabled,
            evaluation_notify_mode=payload.evaluation_notify_mode,
            evaluation_top_n=payload.evaluation_top_n,
            evaluation_min_strength=payload.evaluation_min_strength,
            ir_urls=payload.ir_urls,
            x_official_account=payload.x_official_account,
            x_executive_accounts=[row.model_dump() for row in payload.x_executive_accounts],
            reason=payload.reason,
        )
    _run_watchlist_registration_warmup(request=request, item=created)
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
            priority=payload.priority,
            always_notify_enabled=payload.always_notify_enabled,
            ai_enabled=True,
            is_active=payload.is_active,
            evaluation_enabled=payload.evaluation_enabled,
            evaluation_notify_mode=payload.evaluation_notify_mode,
            evaluation_top_n=payload.evaluation_top_n,
            evaluation_min_strength=payload.evaluation_min_strength,
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
    return _resolve_status_dependency_from_app(
        app=request.app,
        value_key=value_key,
        factory_key=factory_key,
    )


def _resolve_status_dependency_from_app(
    *,
    app: Any,
    value_key: str,
    factory_key: str,
):
    dependency = getattr(app.state, value_key, None)
    if dependency is not None:
        return dependency

    factory = getattr(app.state, factory_key, None)
    if factory is None:
        raise InternalServerError(f"{value_key} の依存解決に失敗しました。")
    try:
        dependency = factory()
    except Exception as exc:
        raise InternalServerError(f"{value_key} の初期化に失敗しました。") from exc
    setattr(app.state, value_key, dependency)
    return dependency


def _build_watchlist_item_response(
    *,
    item: WatchlistItem,
    latest_metric: DailyMetric | None,
    latest_medians: MetricMedians | None,
    latest_signal_state: SignalState | None,
    next_earnings: EarningsCalendarEntry | None,
    notification_skip_reason: str | None = None,
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
    next_earnings_days = _resolve_next_earnings_days(next_earnings_date=next_earnings_date)

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
        notification_skip_reason=notification_skip_reason,
        next_earnings_date=next_earnings_date,
        next_earnings_time=next_earnings_time,
        next_earnings_days=next_earnings_days,
    )


def _build_watchlist_item_response_with_optional_status(
    *,
    request: Request,
    item: WatchlistItem,
) -> WatchlistItemResponse:
    try:
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
    except InternalServerError:
        LOGGER.warning("watchlist詳細ステータス取得をスキップ: ticker=%s", item.ticker)
        return WatchlistItemResponse.from_domain(item)

    today_jst = datetime.now(JST).date().isoformat()
    latest_metric = _load_latest_metrics_by_ticker(daily_metrics_repo, [item.ticker]).get(item.ticker)
    latest_medians = _load_latest_medians_by_ticker(metric_medians_repo, [item.ticker]).get(item.ticker)
    latest_signal_state = _load_latest_signal_states_by_ticker(signal_state_repo, [item.ticker]).get(item.ticker)
    next_earnings = _load_next_earnings_by_ticker(earnings_calendar_repo, [item.ticker], from_date=today_jst).get(item.ticker)

    return _build_watchlist_item_response(
        item=item,
        latest_metric=latest_metric,
        latest_medians=latest_medians,
        latest_signal_state=latest_signal_state,
        next_earnings=next_earnings,
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


def _load_recent_notifications_by_ticker_optional(
    *,
    request: Request,
    tickers: list[str],
) -> dict[str, list[NotificationLogEntry]]:
    try:
        repository = _resolve_status_dependency(
            request=request,
            value_key="notification_log_repository",
            factory_key="notification_log_repository_factory",
        )
    except InternalServerError as exc:
        LOGGER.warning("通知スキップ理由の取得をスキップ: reason=%s", exc)
        return {}

    rows_by_ticker: dict[str, list[NotificationLogEntry]] = {}
    for ticker in tickers:
        try:
            list_recent = getattr(repository, "list_recent", None)
            if callable(list_recent):
                rows = _call_repository(list_recent, ticker=ticker, limit=100)
            else:
                rows = _call_repository(repository.list_timeline, ticker=ticker, limit=100, offset=0)
        except InternalServerError as exc:
            LOGGER.warning("通知スキップ理由の取得をスキップ: ticker=%s reason=%s", ticker, exc)
            rows = []
        rows_by_ticker[ticker] = rows
    return rows_by_ticker


def _load_technical_alert_rules_optional(*, request: Request, ticker: str) -> list[TechnicalAlertRule]:
    try:
        repository = _resolve_status_dependency(
            request=request,
            value_key="technical_alert_rules_repository",
            factory_key="technical_alert_rules_repository_factory",
        )
    except InternalServerError as exc:
        LOGGER.warning("technical alert rules の取得をスキップ: ticker=%s reason=%s", ticker, exc)
        return []

    try:
        list_recent = getattr(repository, "list_recent", None)
        if callable(list_recent):
            return _call_repository(list_recent, ticker=ticker, limit=100)
        return []
    except InternalServerError as exc:
        LOGGER.warning("technical alert rules の取得をスキップ: ticker=%s reason=%s", ticker, exc)
        return []


def _load_latest_technical_optional(*, request: Request, ticker: str) -> TechnicalIndicatorsDaily | None:
    try:
        repository = _resolve_status_dependency(
            request=request,
            value_key="technical_indicators_repository",
            factory_key="technical_indicators_repository_factory",
        )
    except InternalServerError as exc:
        LOGGER.warning("latest technical の取得をスキップ: ticker=%s reason=%s", ticker, exc)
        return None

    try:
        rows = _call_repository(repository.list_recent, ticker=ticker, limit=1)
    except InternalServerError as exc:
        LOGGER.warning("latest technical の取得をスキップ: ticker=%s reason=%s", ticker, exc)
        return None
    return rows[0] if rows else None


def _resolve_cooldown_hours(*, request: Request) -> int:
    app_settings = load_settings()
    fallback = app_settings.cooldown_hours
    try:
        repository = _resolve_status_dependency(
            request=request,
            value_key="global_settings_repository",
            factory_key="global_settings_repository_factory",
        )
    except InternalServerError:
        return fallback

    try:
        global_settings = repository.get_global_settings()
    except Exception as exc:
        LOGGER.warning("global_settings/runtime 取得失敗のため環境変数設定を使用: reason=%s", exc)
        return fallback

    return resolve_runtime_settings(
        default_cooldown_hours=fallback,
        default_intel_notification_max_age_days=app_settings.intel_notification_max_age_days,
        global_settings=global_settings,
    ).cooldown_hours


def _resolve_notification_skip_reason(
    *,
    item: WatchlistItem,
    latest_metric: DailyMetric | None,
    latest_medians: MetricMedians | None,
    latest_signal_state: SignalState | None,
    recent_notifications: list[NotificationLogEntry],
    cooldown_hours: int,
    now_iso: str,
) -> str | None:
    if not item.is_active:
        return "監視OFF（is_active=false）"
    if item.notify_channel is NotifyChannel.OFF:
        return "通知チャネルOFF"
    if item.notify_timing is NotifyTiming.OFF:
        return "通知タイミングOFF"

    current_metric_value = _resolve_current_metric_value(item=item, latest_metric=latest_metric)
    insufficient_windows = _resolve_insufficient_windows(latest_medians)
    state_is_current = _is_state_aligned_with_latest_metric(
        latest_signal_state=latest_signal_state,
        latest_metric=latest_metric,
    )

    if (
        state_is_current
        and latest_signal_state is not None
        and latest_signal_state.category
        and latest_signal_state.combo
    ):
        decision = evaluate_cooldown(
            now_iso=now_iso,
            cooldown_hours=cooldown_hours,
            candidate_ticker=item.ticker,
            candidate_category=latest_signal_state.category,
            candidate_condition_key=f"{latest_signal_state.metric_type.value}:{latest_signal_state.combo}",
            candidate_is_strong=latest_signal_state.is_strong,
            recent_entries=recent_notifications,
        )
        if not decision.should_send:
            return decision.reason
        return None

    if item.always_notify_enabled:
        status_state = (
            latest_signal_state
            if state_is_current and latest_signal_state is not None
            else _build_fallback_signal_state(
            item=item,
            metric_value=current_metric_value,
            trade_date=latest_metric.trade_date if latest_metric is not None else datetime.now(JST).date().isoformat(),
            now_iso=now_iso,
        )
        )
        status_message = format_signal_status_message(
            ticker=item.ticker,
            company_name=item.name,
            state=status_state,
            metric_value=current_metric_value,
            median_1w=latest_medians.median_1w if latest_medians is not None else None,
            median_3m=latest_medians.median_3m if latest_medians is not None else None,
            median_1y=latest_medians.median_1y if latest_medians is not None else None,
            insufficient_windows=insufficient_windows,
        )
        decision = evaluate_cooldown(
            now_iso=now_iso,
            cooldown_hours=cooldown_hours,
            candidate_ticker=item.ticker,
            candidate_category=status_message.category,
            candidate_condition_key=status_message.condition_key,
            candidate_is_strong=False,
            recent_entries=recent_notifications,
        )
        if not decision.should_send:
            return decision.reason
        if current_metric_value is None:
            return "データ不足（【データ不明】通知対象）"
        return None

    if current_metric_value is None:
        return "データ不足（【データ不明】通知対象）"

    if insufficient_windows:
        return f"条件未達（中央値不足: {'/'.join(insufficient_windows)}）"

    return "条件未達（割安シグナルなし）"


def _resolve_current_metric_value(*, item: WatchlistItem, latest_metric: DailyMetric | None) -> float | None:
    if latest_metric is None:
        return None
    return latest_metric.per_value if item.metric_type is MetricType.PER else latest_metric.psr_value


def _is_state_aligned_with_latest_metric(
    *,
    latest_signal_state: SignalState | None,
    latest_metric: DailyMetric | None,
) -> bool:
    if latest_signal_state is None or latest_metric is None:
        return False
    return latest_signal_state.trade_date == latest_metric.trade_date


def _resolve_insufficient_windows(latest_medians: MetricMedians | None) -> list[str]:
    if latest_medians is None:
        return ["1W", "3M", "1Y"]
    return latest_medians.insufficient_windows()


def _resolve_next_earnings_days(*, next_earnings_date: str | None) -> int | None:
    if not next_earnings_date:
        return None
    try:
        target_date = datetime.fromisoformat(next_earnings_date).date()
    except ValueError:
        return None
    today = datetime.now(JST).date()
    return max((target_date - today).days, 0)


def _build_fallback_signal_state(
    *,
    item: WatchlistItem,
    metric_value: float | None,
    trade_date: str,
    now_iso: str,
) -> SignalState:
    return SignalState(
        ticker=item.ticker,
        trade_date=trade_date,
        metric_type=item.metric_type,
        metric_value=metric_value,
        under_1w=False,
        under_3m=False,
        under_1y=False,
        combo=None,
        is_strong=False,
        category=None,
        streak_days=0,
        updated_at=now_iso,
    )


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


def _run_watchlist_registration_warmup(*, request: Request, item: WatchlistItem) -> None:
    settings = load_settings()
    api_key = os.environ.get("JQUANTS_API_KEY", "").strip()
    thread = threading.Thread(
        target=_run_watchlist_registration_warmup_worker,
        kwargs={
            "app": request.app,
            "item": item,
            "timezone_name": settings.timezone,
            "window_1w_days": settings.window_1w_days,
            "window_3m_days": settings.window_3m_days,
            "window_1y_days": settings.window_1y_days,
            "api_key": api_key,
        },
        daemon=True,
    )
    try:
        thread.start()
    except Exception as exc:
        LOGGER.exception("登録直後ウォームアップ開始失敗: ticker=%s error=%s", item.ticker, exc)


def _run_watchlist_registration_warmup_worker(
    *,
    app: Any,
    item: WatchlistItem,
    timezone_name: str,
    window_1w_days: int,
    window_3m_days: int,
    window_1y_days: int,
    api_key: str,
) -> None:
    trade_date = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    try:
        daily_metrics_repo = _resolve_status_dependency_from_app(
            app=app,
            value_key="daily_metrics_repository",
            factory_key="daily_metrics_repository_factory",
        )
        metric_medians_repo = _resolve_status_dependency_from_app(
            app=app,
            value_key="metric_medians_repository",
            factory_key="metric_medians_repository_factory",
        )
        signal_state_repo = _resolve_status_dependency_from_app(
            app=app,
            value_key="signal_state_repository",
            factory_key="signal_state_repository_factory",
        )
    except InternalServerError as exc:
        LOGGER.warning("登録直後ウォームアップをスキップ: ticker=%s reason=%s", item.ticker, exc)
        return

    try:
        upsert_latest_snapshot_metric(
            item=item,
            trade_date=trade_date,
            market_data_source=create_default_market_data_source(jquants_api_key=api_key),
            daily_metrics_repo=daily_metrics_repo,
        )
        refresh_latest_medians_and_signal(
            item=item,
            daily_metrics_repo=daily_metrics_repo,
            medians_repo=metric_medians_repo,
            signal_state_repo=signal_state_repo,
            window_1w_days=window_1w_days,
            window_3m_days=window_3m_days,
            window_1y_days=window_1y_days,
        )
        LOGGER.info("登録直後ウォームアップ完了: ticker=%s trade_date=%s", item.ticker, trade_date)
    except Exception as exc:
        LOGGER.exception("登録直後ウォームアップ失敗: ticker=%s error=%s", item.ticker, exc)

    if not api_key:
        LOGGER.warning("JQUANTS_API_KEY 未設定のため、登録直後バックフィルをスキップ: ticker=%s", item.ticker)
        return

    if not _is_watchlist_registration_backfill_enabled():
        LOGGER.info("登録直後バックフィルは無効設定のためスキップ: ticker=%s", item.ticker)
        return

    _run_watchlist_registration_backfill_worker(
        item=item,
        api_key=api_key,
        timezone_name=timezone_name,
        window_1w_days=window_1w_days,
        window_3m_days=window_3m_days,
        window_1y_days=window_1y_days,
    )


def _run_watchlist_registration_backfill_worker(
    *,
    item: WatchlistItem,
    api_key: str,
    timezone_name: str,
    window_1w_days: int,
    window_3m_days: int,
    window_1y_days: int,
) -> None:
    to_date = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    from_date = resolve_incremental_from_date(
        latest_trade_date=None,
        to_date=to_date,
        initial_lookback_days=DEFAULT_INITIAL_LOOKBACK_DAYS,
        overlap_days=0,
    )
    try:
        client = create_firestore_client()
        daily_metrics_repo = FirestoreDailyMetricsRepository(client)
        metric_medians_repo = FirestoreMetricMediansRepository(client)
        signal_state_repo = FirestoreSignalStateRepository(client)
        jquants_client = JQuantsV2Client(api_key=api_key)
        result = backfill_ticker_from_jquants(
            item=item,
            from_date=from_date,
            to_date=to_date,
            jquants_client=jquants_client,
            daily_metrics_repo=daily_metrics_repo,
        )
        refresh_latest_medians_and_signal(
            item=item,
            daily_metrics_repo=daily_metrics_repo,
            medians_repo=metric_medians_repo,
            signal_state_repo=signal_state_repo,
            window_1w_days=window_1w_days,
            window_3m_days=window_3m_days,
            window_1y_days=window_1y_days,
        )
        LOGGER.info(
            "登録直後バックフィル完了: ticker=%s from=%s to=%s generated=%s upserted=%s",
            item.ticker,
            result.from_date,
            result.to_date,
            result.generated,
            result.upserted,
        )
    except Exception as exc:
        LOGGER.exception(
            "登録直後バックフィル失敗: ticker=%s from=%s to=%s error=%s",
            item.ticker,
            from_date,
            to_date,
            exc,
        )


def _is_watchlist_registration_backfill_enabled() -> bool:
    raw_value = os.environ.get("WATCHLIST_REGISTRATION_BACKFILL_ENABLED", "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}

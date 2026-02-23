from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from hashlib import sha1
import logging
from typing import Protocol

from kabu_per_bot.earnings import EarningsCalendarEntry, select_next_week_entries, select_tomorrow_entries
from kabu_per_bot.market_data import MarketDataError, MarketDataSource
from kabu_per_bot.metrics import DailyMetric, MetricMedians, build_daily_metric, calculate_metric_medians
from kabu_per_bot.notification import (
    NotificationMessage,
    format_data_unknown_message,
    format_earnings_message,
    format_signal_message,
    format_signal_status_message,
)
from kabu_per_bot.signal import (
    NotificationLogEntry,
    SignalState,
    build_signal_state,
    evaluate_cooldown,
    evaluate_signal,
)
from kabu_per_bot.storage.firestore_schema import normalize_trade_date
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


LOGGER = logging.getLogger(__name__)


class NotificationExecutionMode(str, Enum):
    ALL = "ALL"
    DAILY = "DAILY"
    AT_21 = "AT_21"


class MessageSender(Protocol):
    def send(self, message: str) -> None:
        """Send outbound message."""


class DailyMetricsRepository(Protocol):
    def upsert(self, metric: DailyMetric) -> None:
        """Persist metric row."""

    def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
        """Get recent metric rows."""


class MetricMediansRepository(Protocol):
    def upsert(self, medians: MetricMedians) -> None:
        """Persist medians row."""


class SignalStateRepository(Protocol):
    def upsert(self, state: SignalState) -> None:
        """Persist signal state row."""

    def get_latest(self, ticker: str) -> SignalState | None:
        """Get latest signal state."""


class NotificationLogRepository(Protocol):
    def append(self, entry: NotificationLogEntry) -> None:
        """Persist notification log."""

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        """Get recent notification log rows."""


@dataclass(frozen=True)
class DailyPipelineConfig:
    trade_date: str
    window_1w_days: int
    window_3m_days: int
    window_1y_days: int
    cooldown_hours: int
    now_iso: str
    channel: str = "DISCORD"
    execution_mode: NotificationExecutionMode = NotificationExecutionMode.ALL


@dataclass(frozen=True)
class PipelineResult:
    processed_tickers: int = 0
    sent_notifications: int = 0
    skipped_notifications: int = 0
    errors: int = 0

    def merge(self, other: "PipelineResult") -> "PipelineResult":
        return PipelineResult(
            processed_tickers=self.processed_tickers + other.processed_tickers,
            sent_notifications=self.sent_notifications + other.sent_notifications,
            skipped_notifications=self.skipped_notifications + other.skipped_notifications,
            errors=self.errors + other.errors,
        )


def run_daily_pipeline(
    *,
    watchlist_items: list[WatchlistItem],
    market_data_source: MarketDataSource,
    daily_metrics_repo: DailyMetricsRepository,
    medians_repo: MetricMediansRepository,
    signal_state_repo: SignalStateRepository,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    config: DailyPipelineConfig,
) -> PipelineResult:
    result = PipelineResult()
    for item in watchlist_items:
        if not item.is_active:
            continue
        if not _is_channel_enabled(item, config.channel):
            continue
        if not _should_dispatch_for_timing(item.notify_timing, config.execution_mode):
            continue
        try:
            ticker_result = _process_single_ticker(
                watch_item=item,
                market_data_source=market_data_source,
                daily_metrics_repo=daily_metrics_repo,
                medians_repo=medians_repo,
                signal_state_repo=signal_state_repo,
                notification_log_repo=notification_log_repo,
                sender=sender,
                config=config,
            )
        except Exception as exc:
            LOGGER.exception("銘柄処理失敗: ticker=%s error=%s", item.ticker, exc)
            ticker_result = PipelineResult(processed_tickers=1, errors=1)
        result = result.merge(ticker_result)
    return result


def run_weekly_earnings_pipeline(
    *,
    today: str,
    watchlist_items: list[WatchlistItem],
    earnings_entries: list[EarningsCalendarEntry],
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    cooldown_hours: int,
    now_iso: str | None = None,
    channel: str = "DISCORD",
    execution_mode: NotificationExecutionMode | str = NotificationExecutionMode.ALL,
) -> PipelineResult:
    target_entries = select_next_week_entries(earnings_entries, today=today)
    return _run_earnings_pipeline(
        watchlist_items=watchlist_items,
        entries=target_entries,
        category="今週決算",
        notification_log_repo=notification_log_repo,
        sender=sender,
        cooldown_hours=cooldown_hours,
        now_iso=now_iso,
        channel=channel,
        execution_mode=execution_mode,
    )


def run_tomorrow_earnings_pipeline(
    *,
    today: str,
    watchlist_items: list[WatchlistItem],
    earnings_entries: list[EarningsCalendarEntry],
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    cooldown_hours: int,
    now_iso: str | None = None,
    channel: str = "DISCORD",
    execution_mode: NotificationExecutionMode | str = NotificationExecutionMode.ALL,
) -> PipelineResult:
    target_entries = select_tomorrow_entries(earnings_entries, today=today)
    return _run_earnings_pipeline(
        watchlist_items=watchlist_items,
        entries=target_entries,
        category="明日決算",
        notification_log_repo=notification_log_repo,
        sender=sender,
        cooldown_hours=cooldown_hours,
        now_iso=now_iso,
        channel=channel,
        execution_mode=execution_mode,
    )


def _process_single_ticker(
    *,
    watch_item: WatchlistItem,
    market_data_source: MarketDataSource,
    daily_metrics_repo: DailyMetricsRepository,
    medians_repo: MetricMediansRepository,
    signal_state_repo: SignalStateRepository,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    config: DailyPipelineConfig,
) -> PipelineResult:
    sent_count = 0
    skipped_count = 0
    error_count = 0
    trade_date = normalize_trade_date(config.trade_date)

    try:
        snapshot = market_data_source.fetch_snapshot(watch_item.ticker)
    except MarketDataError as exc:
        LOGGER.error("市場データ取得失敗: ticker=%s error=%s", watch_item.ticker, exc)
        unknown_message = format_data_unknown_message(
            ticker=watch_item.ticker,
            company_name=watch_item.name,
            missing_fields=["market_data_source"],
            context=str(exc),
        )
        sent, skipped = _dispatch_with_cooldown(
            message=unknown_message,
            ticker=watch_item.ticker,
            is_strong=False,
            notification_log_repo=notification_log_repo,
            sender=sender,
            cooldown_hours=config.cooldown_hours,
            now_iso=config.now_iso,
            channel=config.channel,
        )
        return PipelineResult(processed_tickers=1, sent_notifications=sent, skipped_notifications=skipped, errors=1)

    metric_row = build_daily_metric(
        ticker=watch_item.ticker,
        trade_date=trade_date,
        metric_type=watch_item.metric_type,
        snapshot=snapshot,
    )
    daily_metrics_repo.upsert(metric_row)

    missing_fields = metric_row.missing_fields(metric_type=watch_item.metric_type)
    if not snapshot.earnings_date:
        missing_fields.append("earnings_date")
    earnings_days = _resolve_earnings_days(trade_date=trade_date, earnings_date=snapshot.earnings_date)
    if missing_fields:
        unknown_message = format_data_unknown_message(
            ticker=watch_item.ticker,
            company_name=watch_item.name,
            missing_fields=missing_fields,
            context="日次指標計算",
            earnings_days=earnings_days,
        )
        sent, skipped = _dispatch_with_cooldown(
            message=unknown_message,
            ticker=watch_item.ticker,
            is_strong=False,
            notification_log_repo=notification_log_repo,
            sender=sender,
            cooldown_hours=config.cooldown_hours,
            now_iso=config.now_iso,
            channel=config.channel,
            data_source=metric_row.data_source,
            data_fetched_at=metric_row.fetched_at,
        )
        return PipelineResult(processed_tickers=1, sent_notifications=sent, skipped_notifications=skipped, errors=0)

    recent_metrics = daily_metrics_repo.list_recent(watch_item.ticker, limit=config.window_1y_days)
    medians = calculate_metric_medians(
        ticker=watch_item.ticker,
        trade_date=trade_date,
        metric_type=watch_item.metric_type,
        latest_first_metrics=recent_metrics,
        window_1w_days=config.window_1w_days,
        window_3m_days=config.window_3m_days,
        window_1y_days=config.window_1y_days,
    )
    medians_repo.upsert(medians)

    metric_value = metric_row.per_value if watch_item.metric_type is MetricType.PER else metric_row.psr_value
    evaluation = evaluate_signal(
        ticker=watch_item.ticker,
        trade_date=trade_date,
        metric_type=watch_item.metric_type,
        metric_value=metric_value,
        medians=medians,
    )
    previous_state = signal_state_repo.get_latest(watch_item.ticker)
    state = build_signal_state(evaluation=evaluation, previous_state=previous_state)
    signal_state_repo.upsert(state)

    if state.category and state.combo:
        signal_phase = "継続" if state.streak_days > 1 else "新規"
        message = format_signal_message(
            ticker=watch_item.ticker,
            company_name=watch_item.name,
            state=state,
            signal_phase=signal_phase,
            metric_value=state.metric_value,
            median_1w=medians.median_1w,
            median_3m=medians.median_3m,
            median_1y=medians.median_1y,
            earnings_days=earnings_days,
        )
        sent_count, skipped_count = _dispatch_with_cooldown(
            message=message,
            ticker=watch_item.ticker,
            is_strong=state.is_strong,
            notification_log_repo=notification_log_repo,
            sender=sender,
            cooldown_hours=config.cooldown_hours,
            now_iso=config.now_iso,
            channel=config.channel,
            data_source=metric_row.data_source,
            data_fetched_at=metric_row.fetched_at,
        )
    elif watch_item.always_notify_enabled:
        insufficient_windows = medians.insufficient_windows()
        signal_phase = _resolve_status_signal_phase(
            previous_state=previous_state,
            current_state=state,
            insufficient_windows=insufficient_windows,
        )
        status_message = format_signal_status_message(
            ticker=watch_item.ticker,
            company_name=watch_item.name,
            state=state,
            metric_value=state.metric_value,
            median_1w=medians.median_1w,
            median_3m=medians.median_3m,
            median_1y=medians.median_1y,
            insufficient_windows=insufficient_windows,
            signal_phase=signal_phase,
            earnings_days=earnings_days,
        )
        sent_count, skipped_count = _dispatch_with_cooldown(
            message=status_message,
            ticker=watch_item.ticker,
            is_strong=False,
            notification_log_repo=notification_log_repo,
            sender=sender,
            cooldown_hours=config.cooldown_hours,
            now_iso=config.now_iso,
            channel=config.channel,
            data_source=metric_row.data_source,
            data_fetched_at=metric_row.fetched_at,
        )

    return PipelineResult(
        processed_tickers=1,
        sent_notifications=sent_count,
        skipped_notifications=skipped_count,
        errors=error_count,
    )


def _run_earnings_pipeline(
    *,
    watchlist_items: list[WatchlistItem],
    entries: list[EarningsCalendarEntry],
    category: str,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    cooldown_hours: int,
    now_iso: str | None,
    channel: str,
    execution_mode: NotificationExecutionMode | str,
) -> PipelineResult:
    now_value = now_iso or datetime.now(timezone.utc).isoformat()
    watch_map = {item.ticker: item for item in watchlist_items if item.is_active}
    result = PipelineResult()
    for entry in entries:
        watch_item = watch_map.get(entry.ticker)
        if watch_item is None:
            continue
        if not _is_channel_enabled(watch_item, channel):
            continue
        if not _should_dispatch_for_timing(watch_item.notify_timing, execution_mode):
            continue
        try:
            message = format_earnings_message(
                ticker=entry.ticker,
                company_name=watch_item.name,
                earnings_date=entry.earnings_date,
                earnings_time=entry.earnings_time,
                category=category,
                quarter=entry.quarter,
            )
            sent, skipped = _dispatch_with_cooldown(
                message=message,
                ticker=entry.ticker,
                is_strong=False,
                notification_log_repo=notification_log_repo,
                sender=sender,
                cooldown_hours=cooldown_hours,
                now_iso=now_value,
                channel=channel,
                data_source=entry.source,
                data_fetched_at=entry.fetched_at,
            )
            result = result.merge(
                PipelineResult(processed_tickers=1, sent_notifications=sent, skipped_notifications=skipped)
            )
        except Exception as exc:
            LOGGER.exception("決算通知処理失敗: ticker=%s error=%s", entry.ticker, exc)
            result = result.merge(PipelineResult(processed_tickers=1, errors=1))
    return result


def _dispatch_with_cooldown(
    *,
    message: NotificationMessage,
    ticker: str,
    is_strong: bool,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    cooldown_hours: int,
    now_iso: str,
    channel: str,
    data_source: str | None = None,
    data_fetched_at: str | None = None,
) -> tuple[int, int]:
    recent = notification_log_repo.list_recent(ticker, limit=100)
    decision = evaluate_cooldown(
        now_iso=now_iso,
        cooldown_hours=cooldown_hours,
        candidate_ticker=ticker,
        candidate_category=message.category,
        candidate_condition_key=message.condition_key,
        candidate_is_strong=is_strong,
        recent_entries=recent,
    )
    if not decision.should_send:
        LOGGER.info("通知スキップ: ticker=%s category=%s reason=%s", ticker, message.category, decision.reason)
        return (0, 1)

    sender.send(message.body)
    log_entry = NotificationLogEntry(
        entry_id=_notification_id(message=message, channel=channel, sent_at=now_iso),
        ticker=message.ticker,
        category=message.category,
        condition_key=message.condition_key,
        sent_at=now_iso,
        channel=channel,
        payload_hash=message.payload_hash,
        is_strong=is_strong,
        body=message.body,
        data_source=data_source,
        data_fetched_at=data_fetched_at,
    )
    notification_log_repo.append(log_entry)
    return (1, 0)


def _notification_id(*, message: NotificationMessage, channel: str, sent_at: str) -> str:
    raw = f"{message.ticker}|{message.category}|{message.condition_key}|{channel}|{sent_at}"
    return sha1(raw.encode("utf-8")).hexdigest()


def _is_channel_enabled(item: WatchlistItem, channel: str) -> bool:
    normalized = channel.strip().upper()
    if item.notify_channel is NotifyChannel.OFF:
        return False
    if normalized.startswith("DISCORD"):
        return item.notify_channel is NotifyChannel.DISCORD
    return False


def _should_dispatch_for_timing(
    notify_timing: NotifyTiming,
    execution_mode: NotificationExecutionMode | str,
) -> bool:
    mode = _normalize_execution_mode(execution_mode)
    if notify_timing is NotifyTiming.OFF:
        return False
    if mode is NotificationExecutionMode.ALL:
        return True
    if mode is NotificationExecutionMode.DAILY:
        return notify_timing is NotifyTiming.IMMEDIATE
    return notify_timing is NotifyTiming.AT_21


def _normalize_execution_mode(execution_mode: NotificationExecutionMode | str) -> NotificationExecutionMode:
    if isinstance(execution_mode, NotificationExecutionMode):
        return execution_mode
    try:
        return NotificationExecutionMode(str(execution_mode).strip().upper())
    except ValueError as exc:
        raise ValueError(f"unsupported execution_mode: {execution_mode}") from exc


def _resolve_status_signal_phase(
    *,
    previous_state: SignalState | None,
    current_state: SignalState,
    insufficient_windows: list[str],
) -> str | None:
    if insufficient_windows:
        return None
    if not _has_active_signal(previous_state, metric_type=current_state.metric_type):
        return None
    if previous_state is None:
        return None
    if not _is_previous_business_day(
        previous_trade_date=previous_state.trade_date,
        current_trade_date=current_state.trade_date,
    ):
        return None
    return "解除"


def _has_active_signal(state: SignalState | None, *, metric_type: MetricType) -> bool:
    if state is None:
        return False
    if state.metric_type is not metric_type:
        return False
    return bool(state.category and state.combo)


def _resolve_earnings_days(*, trade_date: str, earnings_date: str | None) -> int | None:
    if not earnings_date:
        return None
    try:
        base_date = date.fromisoformat(trade_date)
        target_date = date.fromisoformat(earnings_date)
    except ValueError:
        return None
    return max((target_date - base_date).days, 0)


def _is_previous_business_day(*, previous_trade_date: str, current_trade_date: str) -> bool:
    previous = date.fromisoformat(previous_trade_date)
    current = date.fromisoformat(current_trade_date)
    expected = current - timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    return previous == expected

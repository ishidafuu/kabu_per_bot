from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from kabu_per_bot.backfill import build_daily_metrics_from_jquants_v2
from kabu_per_bot.jquants_v2 import JQuantsV2Client
from kabu_per_bot.market_data import MarketDataSource
from kabu_per_bot.metrics import DailyMetric, MetricMedians, build_daily_metric, calculate_metric_medians
from kabu_per_bot.signal import SignalState, build_signal_state, evaluate_signal
from kabu_per_bot.storage.firestore_schema import normalize_trade_date
from kabu_per_bot.watchlist import MetricType, WatchlistItem


DEFAULT_INITIAL_LOOKBACK_DAYS = 400
DEFAULT_OVERLAP_DAYS = 7


class DailyMetricsRepository(Protocol):
    def upsert(self, metric: DailyMetric) -> None:
        """Persist metric row."""

    def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
        """Get recent metric rows."""


class MetricMediansRepository(Protocol):
    def upsert(self, medians: MetricMedians) -> None:
        """Persist medians row."""


class SignalStateRepository(Protocol):
    def get_latest(self, ticker: str) -> SignalState | None:
        """Get latest signal state."""

    def upsert(self, state: SignalState) -> None:
        """Persist signal state."""


@dataclass(frozen=True)
class BackfillExecutionResult:
    ticker: str
    from_date: str
    to_date: str
    generated: int
    upserted: int


def resolve_incremental_from_date(
    *,
    latest_trade_date: str | None,
    to_date: str,
    initial_lookback_days: int = DEFAULT_INITIAL_LOOKBACK_DAYS,
    overlap_days: int = DEFAULT_OVERLAP_DAYS,
) -> str:
    if initial_lookback_days <= 0:
        raise ValueError("initial_lookback_days must be > 0.")
    if overlap_days < 0:
        raise ValueError("overlap_days must be >= 0.")

    normalized_to = normalize_trade_date(to_date)
    to_day = date.fromisoformat(normalized_to)
    if latest_trade_date is None:
        return (to_day - timedelta(days=initial_lookback_days)).isoformat()

    latest_day = date.fromisoformat(normalize_trade_date(latest_trade_date))
    from_day = latest_day - timedelta(days=overlap_days)
    if from_day > to_day:
        return normalized_to
    return from_day.isoformat()


def backfill_ticker_from_jquants(
    *,
    item: WatchlistItem,
    from_date: str,
    to_date: str,
    jquants_client: JQuantsV2Client,
    daily_metrics_repo: DailyMetricsRepository,
    fetched_at: str | None = None,
    dry_run: bool = False,
) -> BackfillExecutionResult:
    normalized_from = normalize_trade_date(from_date)
    normalized_to = normalize_trade_date(to_date)
    resolved_fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()

    bars_daily = jquants_client.get_eq_bars_daily(
        code_or_ticker=item.ticker,
        from_date=normalized_from,
        to_date=normalized_to,
    )
    fin_summary = jquants_client.get_fin_summary(
        code_or_ticker=item.ticker,
        from_date=normalized_from,
        to_date=normalized_to,
    )
    metrics = build_daily_metrics_from_jquants_v2(
        ticker=item.ticker,
        metric_type=item.metric_type,
        bars_daily_rows=bars_daily,
        fin_summary_rows=fin_summary,
        fetched_at=resolved_fetched_at,
    )

    upserted = 0
    if not dry_run:
        for metric in metrics:
            daily_metrics_repo.upsert(metric)
            upserted += 1

    return BackfillExecutionResult(
        ticker=item.ticker,
        from_date=normalized_from,
        to_date=normalized_to,
        generated=len(metrics),
        upserted=upserted,
    )


def upsert_latest_snapshot_metric(
    *,
    item: WatchlistItem,
    trade_date: str,
    market_data_source: MarketDataSource,
    daily_metrics_repo: DailyMetricsRepository,
) -> DailyMetric:
    snapshot = market_data_source.fetch_snapshot(item.ticker)
    metric = build_daily_metric(
        ticker=item.ticker,
        trade_date=trade_date,
        metric_type=item.metric_type,
        snapshot=snapshot,
    )
    daily_metrics_repo.upsert(metric)
    return metric


def refresh_latest_medians_and_signal(
    *,
    item: WatchlistItem,
    daily_metrics_repo: DailyMetricsRepository,
    medians_repo: MetricMediansRepository,
    signal_state_repo: SignalStateRepository,
    window_1w_days: int,
    window_3m_days: int,
    window_1y_days: int,
) -> bool:
    recent_metrics = daily_metrics_repo.list_recent(item.ticker, limit=window_1y_days)
    if not recent_metrics:
        return False

    latest_metric = recent_metrics[0]
    medians = calculate_metric_medians(
        ticker=item.ticker,
        trade_date=latest_metric.trade_date,
        metric_type=item.metric_type,
        latest_first_metrics=recent_metrics,
        window_1w_days=window_1w_days,
        window_3m_days=window_3m_days,
        window_1y_days=window_1y_days,
    )
    medians_repo.upsert(medians)

    metric_value = latest_metric.per_value if item.metric_type is MetricType.PER else latest_metric.psr_value
    evaluation = evaluate_signal(
        ticker=item.ticker,
        trade_date=latest_metric.trade_date,
        metric_type=item.metric_type,
        metric_value=metric_value,
        medians=medians,
    )
    previous_state = signal_state_repo.get_latest(item.ticker)
    state = build_signal_state(evaluation=evaluation, previous_state=previous_state)
    if (
        previous_state is not None
        and previous_state.trade_date == latest_metric.trade_date
        and previous_state.category == state.category
        and previous_state.combo == state.combo
        and previous_state.is_strong == state.is_strong
    ):
        # Same trade_date re-evaluation should not degrade streak_days.
        state = replace(state, streak_days=previous_state.streak_days)
    signal_state_repo.upsert(state)
    return True

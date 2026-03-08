from __future__ import annotations

from dataclasses import dataclass
import logging

from kabu_per_bot.pipeline import NotificationExecutionMode, PipelineResult
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date
from kabu_per_bot.technical import TechnicalSyncState
from kabu_per_bot.technical_indicators import recalculate_recent_technical_indicators
from kabu_per_bot.technical_pipeline import TechnicalAlertPipelineConfig, run_technical_alert_pipeline
from kabu_per_bot.technical_profiles import TechnicalProfile
from kabu_per_bot.technical_sync import (
    DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS,
    DEFAULT_TECHNICAL_OVERLAP_DAYS,
    resolve_technical_sync_from_date,
    sync_ticker_price_bars,
)
from kabu_per_bot.watchlist import WatchlistItem


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TechnicalTickerJobResult:
    ticker: str
    from_date: str
    to_date: str
    fetched_rows: int
    upserted_rows: int
    indicator_read_rows: int
    indicator_written_rows: int
    latest_fetched_trade_date: str | None
    latest_calculated_trade_date: str | None
    error: str | None = None


@dataclass(frozen=True)
class TechnicalJobResult:
    to_date: str
    full_refresh: bool
    alerts_enabled: bool
    processed_tickers: int
    fetched_rows: int
    upserted_rows: int
    indicator_written_rows: int
    sent_notifications: int
    skipped_notifications: int
    errors: int
    tickers: tuple[TechnicalTickerJobResult, ...]


def select_active_watchlist_items(
    all_items: list[WatchlistItem],
    *,
    target_tickers: list[str],
) -> list[WatchlistItem]:
    active_items = [item for item in all_items if item.is_active]
    if not target_tickers:
        return sorted(active_items, key=lambda item: item.ticker)
    index = {item.ticker: item for item in active_items}
    selected: list[WatchlistItem] = []
    missing: list[str] = []
    for ticker in target_tickers:
        item = index.get(normalize_ticker(ticker))
        if item is None:
            missing.append(normalize_ticker(ticker))
            continue
        selected.append(item)
    if missing:
        raise ValueError(f"watchlistに存在しない、または非アクティブのtickerがあります: {', '.join(missing)}")
    return selected


def run_technical_job(
    *,
    watchlist_items: list[WatchlistItem],
    to_date: str,
    jquants_client,
    price_bars_repo,
    indicators_repo,
    sync_state_repo,
    technical_alert_rules_repo,
    technical_alert_state_repo,
    notification_log_repo,
    technical_profiles_repo,
    sender,
    cooldown_hours: int,
    now_iso: str,
    channel: str,
    execution_mode: NotificationExecutionMode,
    full_refresh: bool = False,
    alerts_enabled: bool = True,
    initial_lookback_days: int = DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS,
    overlap_days: int = DEFAULT_TECHNICAL_OVERLAP_DAYS,
) -> TechnicalJobResult:
    normalized_to_date = normalize_trade_date(to_date)
    total_fetched = 0
    total_upserted = 0
    total_indicator_written = 0
    total_errors = 0
    ticker_results: list[TechnicalTickerJobResult] = []
    successful_items: list[WatchlistItem] = []

    for item in watchlist_items:
        state_before: TechnicalSyncState | None = sync_state_repo.get(item.ticker)
        from_date = resolve_technical_sync_from_date(
            latest_fetched_trade_date=(state_before.latest_fetched_trade_date if state_before is not None else None),
            to_date=normalized_to_date,
            initial_lookback_days=initial_lookback_days,
            overlap_days=overlap_days,
            full_refresh=full_refresh,
        )
        try:
            profile: TechnicalProfile | None = None
            if technical_profiles_repo is not None and item.technical_profile_id is not None:
                profile = technical_profiles_repo.get(item.technical_profile_id)
            sync_result = sync_ticker_price_bars(
                item=item,
                from_date=from_date,
                to_date=normalized_to_date,
                jquants_client=jquants_client,
                price_bars_repo=price_bars_repo,
                sync_state_repo=sync_state_repo,
                full_refresh=full_refresh,
            )
            refresh_result = recalculate_recent_technical_indicators(
                ticker=item.ticker,
                price_bars_repo=price_bars_repo,
                indicators_repo=indicators_repo,
                sync_state_repo=sync_state_repo,
                profile=profile,
                threshold_overrides=item.technical_profile_override_thresholds,
                flag_overrides=item.technical_profile_override_flags,
                strong_alerts_override=item.technical_profile_override_strong_alerts,
                weak_alerts_override=item.technical_profile_override_weak_alerts,
                calculated_at=now_iso,
            )
            total_fetched += sync_result.fetched_rows
            total_upserted += sync_result.upserted_rows
            total_indicator_written += refresh_result.written_rows
            successful_items.append(item)
            ticker_results.append(
                TechnicalTickerJobResult(
                    ticker=item.ticker,
                    from_date=from_date,
                    to_date=normalized_to_date,
                    fetched_rows=sync_result.fetched_rows,
                    upserted_rows=sync_result.upserted_rows,
                    indicator_read_rows=refresh_result.read_rows,
                    indicator_written_rows=refresh_result.written_rows,
                    latest_fetched_trade_date=sync_result.latest_fetched_trade_date,
                    latest_calculated_trade_date=refresh_result.latest_calculated_trade_date,
                )
            )
        except Exception as exc:
            LOGGER.exception(
                "技術ジョブ処理失敗: ticker=%s from=%s to=%s full_refresh=%s error=%s",
                item.ticker,
                from_date,
                normalized_to_date,
                full_refresh,
                exc,
            )
            total_errors += 1
            state_after = sync_state_repo.get(item.ticker)
            ticker_results.append(
                TechnicalTickerJobResult(
                    ticker=item.ticker,
                    from_date=from_date,
                    to_date=normalized_to_date,
                    fetched_rows=0,
                    upserted_rows=0,
                    indicator_read_rows=0,
                    indicator_written_rows=0,
                    latest_fetched_trade_date=(
                        state_after.latest_fetched_trade_date if state_after is not None else None
                    ),
                    latest_calculated_trade_date=(
                        state_after.latest_calculated_trade_date if state_after is not None else None
                    ),
                    error=str(exc),
                )
            )

    alert_result = PipelineResult()
    if alerts_enabled and successful_items:
        alert_result = run_technical_alert_pipeline(
            watchlist_items=successful_items,
            technical_indicators_repo=indicators_repo,
            technical_alert_rules_repo=technical_alert_rules_repo,
            technical_alert_state_repo=technical_alert_state_repo,
            notification_log_repo=notification_log_repo,
            technical_profiles_repo=technical_profiles_repo,
            sender=sender,
            config=TechnicalAlertPipelineConfig(
                trade_date=normalized_to_date,
                cooldown_hours=cooldown_hours,
                now_iso=now_iso,
                channel=channel,
                execution_mode=execution_mode,
            ),
        )

    return TechnicalJobResult(
        to_date=normalized_to_date,
        full_refresh=full_refresh,
        alerts_enabled=alerts_enabled,
        processed_tickers=len(watchlist_items),
        fetched_rows=total_fetched,
        upserted_rows=total_upserted,
        indicator_written_rows=total_indicator_written,
        sent_notifications=alert_result.sent_notifications,
        skipped_notifications=alert_result.skipped_notifications,
        errors=total_errors + alert_result.errors,
        tickers=tuple(ticker_results),
    )

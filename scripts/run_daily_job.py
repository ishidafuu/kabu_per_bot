#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from kabu_per_bot.committee_pipeline import CommitteePipelineConfig, run_committee_pipeline
from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.market_data import create_default_market_data_source
from kabu_per_bot.pipeline import DailyPipelineConfig, NotificationExecutionMode, PipelineResult, run_daily_pipeline
from kabu_per_bot.runtime_settings import resolve_runtime_settings
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_daily_metrics_repository import FirestoreDailyMetricsRepository
from kabu_per_bot.storage.firestore_global_settings_repository import FirestoreGlobalSettingsRepository
from kabu_per_bot.storage.firestore_metric_medians_repository import FirestoreMetricMediansRepository
from kabu_per_bot.storage.firestore_notification_log_repository import FirestoreNotificationLogRepository
from kabu_per_bot.storage.firestore_schema import normalize_trade_date
from kabu_per_bot.storage.firestore_signal_state_repository import FirestoreSignalStateRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository


LOGGER = logging.getLogger(__name__)
JST_TIMEZONE = "Asia/Tokyo"
DISCORD_WEBHOOK_DEFAULT_ENV = "DISCORD_WEBHOOK_URL"
DISCORD_WEBHOOK_DAILY_ENV = "DISCORD_WEBHOOK_URL_DAILY"
DISCORD_DAILY_CHANNEL = "DISCORD_DAILY"


class StdoutSender:
    def send(self, message: str) -> None:
        print("----- notification -----")
        print(message)


class NotificationLogBypassRepository:
    """Preview mode repository that bypasses cooldown and log writes."""

    def list_recent(self, ticker: str, *, limit: int = 100):
        _ = ticker, limit
        return []

    def append(self, entry) -> None:
        _ = entry
        return None


class CachedMarketDataSource:
    """Cache per-ticker market-data snapshots for a single job run."""

    def __init__(self, source) -> None:
        self._source = source
        self._snapshot_cache: dict[str, object] = {}
        self._error_cache: dict[str, Exception] = {}

    @property
    def source_name(self) -> str:
        return getattr(self._source, "source_name", "cached")

    def fetch_snapshot(self, ticker: str):
        normalized = str(ticker).strip().upper()
        if normalized in self._snapshot_cache:
            return self._snapshot_cache[normalized]
        cached_error = self._error_cache.get(normalized)
        if cached_error is not None:
            raise cached_error
        try:
            snapshot = self._source.fetch_snapshot(ticker)
        except Exception as exc:
            self._error_cache[normalized] = exc
            raise
        self._snapshot_cache[normalized] = snapshot
        return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MVP daily pipeline with Firestore persistence.")
    parser.add_argument("--trade-date", default=None, help="Trade date (YYYY-MM-DD). Default: today(JST)")
    parser.add_argument(
        "--now-iso",
        default=None,
        help="Current time in ISO8601 with timezone (e.g. 2026-02-14T21:00:00+09:00). Default: now(UTC)",
    )
    parser.add_argument(
        "--discord-webhook-url",
        default=_resolve_discord_webhook_default(DISCORD_WEBHOOK_DAILY_ENV),
        help=(
            "Discord webhook URL. Required unless --stdout is set. "
            f"Default: {DISCORD_WEBHOOK_DAILY_ENV} (fallback: {DISCORD_WEBHOOK_DEFAULT_ENV})."
        ),
    )
    parser.add_argument(
        "--jquants-api-key",
        default=os.environ.get("JQUANTS_API_KEY", "").strip(),
        help="J-Quants API v2 key. If set, J-Quants is used as first market-data source.",
    )
    parser.add_argument(
        "--execution-mode",
        choices=("all", "daily", "at_21"),
        default="daily",
        help="Dispatch filter mode. all=daily+21, daily=IMMEDIATE only, at_21=AT_21 only.",
    )
    parser.add_argument("--stdout", action="store_true", help="Send notifications to stdout.")
    parser.add_argument(
        "--no-notification-log",
        action="store_true",
        help="Use with --stdout for notification preview. Bypass cooldown and do not read/write notification_log.",
    )
    parser.add_argument(
        "--disable-committee",
        action="store_true",
        help="Disable committee evaluation notifications.",
    )
    return parser.parse_args()


def _resolve_discord_webhook_default(primary_env_key: str) -> str:
    primary = os.environ.get(primary_env_key, "").strip()
    if primary:
        return primary
    return os.environ.get(DISCORD_WEBHOOK_DEFAULT_ENV, "").strip()


def _create_firestore_client(*, project_id: str):
    try:
        from google.cloud import firestore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-cloud-firestore が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc
    return firestore.Client(project=project_id or None)


def _parse_now_iso(now_iso: str | None) -> datetime:
    if now_iso is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(now_iso)
    if parsed.tzinfo is None:
        raise ValueError("now_iso must include timezone offset, e.g. '+09:00'.")
    return parsed


def resolve_now_utc_iso(*, now_iso: str | None = None) -> str:
    now = _parse_now_iso(now_iso)
    return now.astimezone(timezone.utc).isoformat()


def resolve_trade_date(*, trade_date: str | None = None, now_iso: str | None = None, timezone_name: str) -> str:
    if trade_date is not None:
        return normalize_trade_date(trade_date)
    if timezone_name != JST_TIMEZONE:
        raise ValueError(f"timezone_name must be fixed to {JST_TIMEZONE}.")
    tz = ZoneInfo(timezone_name)
    now = _parse_now_iso(now_iso)
    return now.astimezone(tz).date().isoformat()


def _resolve_sender(args: argparse.Namespace):
    if args.stdout:
        LOGGER.info("送信先: stdout")
        return StdoutSender()
    webhook_url = args.discord_webhook_url.strip()
    if not webhook_url:
        raise ValueError(
            "Discord webhook URL が必要です。"
            f"--discord-webhook-url または {DISCORD_WEBHOOK_DAILY_ENV}/{DISCORD_WEBHOOK_DEFAULT_ENV} を設定してください。"
        )
    LOGGER.info("送信先: Discord webhook (channel=%s)", DISCORD_DAILY_CHANNEL)
    return DiscordNotifier(webhook_url)


def _resolve_notification_log_repo(args: argparse.Namespace, base_repo: FirestoreNotificationLogRepository):
    if args.no_notification_log:
        if not args.stdout:
            raise ValueError("--no-notification-log は --stdout と併用してください。")
        LOGGER.info("通知ログ: バイパス（cooldown無効・notification_log未記録）")
        return NotificationLogBypassRepository()
    return base_repo


def _result_payload(result: PipelineResult) -> dict[str, int]:
    return {
        "processed": result.processed_tickers,
        "sent": result.sent_notifications,
        "skipped": result.skipped_notifications,
        "errors": result.errors,
    }


def _resolve_execution_mode(raw: str) -> NotificationExecutionMode:
    mapping = {
        "all": NotificationExecutionMode.ALL,
        "daily": NotificationExecutionMode.DAILY,
        "at_21": NotificationExecutionMode.AT_21,
    }
    return mapping[raw]


def _resolve_runtime_cooldown_hours(*, settings, client) -> int:
    try:
        repository = FirestoreGlobalSettingsRepository(client)
        runtime_settings = resolve_runtime_settings(
            default_cooldown_hours=settings.cooldown_hours,
            global_settings=repository.get_global_settings(),
        )
        LOGGER.info(
            "クールダウン設定: %s時間 (source=%s)",
            runtime_settings.cooldown_hours,
            runtime_settings.source,
        )
        return runtime_settings.cooldown_hours
    except Exception as exc:
        LOGGER.warning("全体設定の取得に失敗したため環境変数設定を使用: %s", exc)
        return settings.cooldown_hours


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    settings = load_settings()
    trade_date = resolve_trade_date(trade_date=args.trade_date, now_iso=args.now_iso, timezone_name=settings.timezone)
    now_iso = resolve_now_utc_iso(now_iso=args.now_iso)
    sender = _resolve_sender(args)

    client = _create_firestore_client(project_id=settings.firestore_project_id)
    cooldown_hours = _resolve_runtime_cooldown_hours(settings=settings, client=client)
    watchlist_repo = FirestoreWatchlistRepository(client)
    daily_repo = FirestoreDailyMetricsRepository(client)
    medians_repo = FirestoreMetricMediansRepository(client)
    signal_repo = FirestoreSignalStateRepository(client)
    log_repo = _resolve_notification_log_repo(args, FirestoreNotificationLogRepository(client))
    watchlist_items = watchlist_repo.list_all()
    market_data_source = CachedMarketDataSource(
        create_default_market_data_source(
            jquants_api_key=getattr(args, "jquants_api_key", ""),
        )
    )

    LOGGER.info("日次ジョブ開始: trade_date=%s watchlist_items=%s", trade_date, len(watchlist_items))
    if not watchlist_items:
        LOGGER.warning("watchlist が0件のため、処理対象はありません。")

    result = run_daily_pipeline(
        watchlist_items=watchlist_items,
        market_data_source=market_data_source,
        daily_metrics_repo=daily_repo,
        medians_repo=medians_repo,
        signal_state_repo=signal_repo,
        notification_log_repo=log_repo,
        sender=sender,
        config=DailyPipelineConfig(
            trade_date=trade_date,
            window_1w_days=settings.window_1w_days,
            window_3m_days=settings.window_3m_days,
            window_1y_days=settings.window_1y_days,
            cooldown_hours=cooldown_hours,
            now_iso=now_iso,
            channel=DISCORD_DAILY_CHANNEL,
            execution_mode=_resolve_execution_mode(args.execution_mode),
        ),
    )
    total_result = result
    if not getattr(args, "disable_committee", False):
        committee_result = run_committee_pipeline(
            watchlist_items=watchlist_items,
            market_data_source=market_data_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=CommitteePipelineConfig(
                trade_date=trade_date,
                now_iso=now_iso,
                cooldown_hours=cooldown_hours,
                channel=DISCORD_DAILY_CHANNEL,
                execution_mode=_resolve_execution_mode(args.execution_mode),
            ),
        )
        LOGGER.info(
            "委員会評価完了: processed=%s sent=%s skipped=%s errors=%s",
            committee_result.processed_tickers,
            committee_result.sent_notifications,
            committee_result.skipped_notifications,
            committee_result.errors,
        )
        total_result = total_result.merge(committee_result)
    payload = _result_payload(total_result)
    print(json.dumps(payload, ensure_ascii=False))
    LOGGER.info(
        "日次ジョブ完了: processed=%s sent=%s skipped=%s errors=%s",
        payload["processed"],
        payload["sent"],
        payload["skipped"],
        payload["errors"],
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.exception("daily job failed: %s", exc)
        raise SystemExit(1) from exc

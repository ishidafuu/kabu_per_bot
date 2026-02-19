#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.immediate_schedule import evaluate_window_schedule
from kabu_per_bot.market_data import create_default_market_data_source
from kabu_per_bot.pipeline import DailyPipelineConfig, NotificationExecutionMode, PipelineResult, run_daily_pipeline
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings, resolve_runtime_settings
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run IMMEDIATE window pipeline with Firestore persistence.")
    parser.add_argument("--trade-date", default=None, help="Trade date (YYYY-MM-DD). Default: today(JST)")
    parser.add_argument(
        "--window",
        choices=("open", "close"),
        required=True,
        help="Immediate window kind to evaluate.",
    )
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
    parser.add_argument("--stdout", action="store_true", help="Send notifications to stdout.")
    parser.add_argument(
        "--no-notification-log",
        action="store_true",
        help="Use with --stdout for notification preview. Bypass cooldown and do not read/write notification_log.",
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


def _resolve_runtime_settings(*, settings, client):
    try:
        runtime_settings = resolve_runtime_settings(
            default_cooldown_hours=settings.cooldown_hours,
            global_settings=FirestoreGlobalSettingsRepository(client).get_global_settings(),
        )
        LOGGER.info(
            "全体設定: cooldown=%s source=%s",
            runtime_settings.cooldown_hours,
            runtime_settings.source,
        )
        return runtime_settings
    except Exception as exc:
        LOGGER.warning("全体設定の取得に失敗したため環境変数設定を使用: %s", exc)
        return resolve_runtime_settings(
            default_cooldown_hours=settings.cooldown_hours,
            global_settings=GlobalRuntimeSettings(),
        )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    settings = load_settings()
    trade_date = resolve_trade_date(trade_date=args.trade_date, now_iso=args.now_iso, timezone_name=settings.timezone)
    now_iso = resolve_now_utc_iso(now_iso=args.now_iso)
    sender = _resolve_sender(args)

    client = _create_firestore_client(project_id=settings.firestore_project_id)
    runtime_settings = _resolve_runtime_settings(settings=settings, client=client)
    window_decision = evaluate_window_schedule(
        schedule=runtime_settings.immediate_schedule,
        window_kind=args.window,
        now_iso=args.now_iso,
    )
    LOGGER.info(
        "IMMEDIATE window判定: window=%s should_run=%s reason=%s",
        args.window,
        window_decision.should_run,
        window_decision.reason,
    )
    if not window_decision.should_run:
        print(json.dumps(_result_payload(PipelineResult()), ensure_ascii=False))
        return 0

    watchlist_repo = FirestoreWatchlistRepository(client)
    daily_repo = FirestoreDailyMetricsRepository(client)
    medians_repo = FirestoreMetricMediansRepository(client)
    signal_repo = FirestoreSignalStateRepository(client)
    log_repo = _resolve_notification_log_repo(args, FirestoreNotificationLogRepository(client))
    watchlist_items = watchlist_repo.list_all()

    LOGGER.info(
        "IMMEDIATEジョブ開始: window=%s trade_date=%s watchlist_items=%s",
        args.window,
        trade_date,
        len(watchlist_items),
    )
    if not watchlist_items:
        LOGGER.warning("watchlist が0件のため、処理対象はありません。")

    result = run_daily_pipeline(
        watchlist_items=watchlist_items,
        market_data_source=create_default_market_data_source(
            jquants_api_key=getattr(args, "jquants_api_key", ""),
        ),
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
            cooldown_hours=runtime_settings.cooldown_hours,
            now_iso=now_iso,
            channel=DISCORD_DAILY_CHANNEL,
            execution_mode=NotificationExecutionMode.DAILY,
        ),
    )
    payload = _result_payload(result)
    print(json.dumps(payload, ensure_ascii=False))
    LOGGER.info(
        "IMMEDIATEジョブ完了: window=%s processed=%s sent=%s skipped=%s errors=%s",
        args.window,
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
        LOGGER.exception("immediate window job failed: %s", exc)
        raise SystemExit(1) from exc

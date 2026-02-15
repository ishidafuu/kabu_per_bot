#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.market_data import create_default_market_data_source
from kabu_per_bot.pipeline import DailyPipelineConfig, NotificationExecutionMode, PipelineResult, run_daily_pipeline
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_daily_metrics_repository import FirestoreDailyMetricsRepository
from kabu_per_bot.storage.firestore_metric_medians_repository import FirestoreMetricMediansRepository
from kabu_per_bot.storage.firestore_notification_log_repository import FirestoreNotificationLogRepository
from kabu_per_bot.storage.firestore_schema import normalize_trade_date
from kabu_per_bot.storage.firestore_signal_state_repository import FirestoreSignalStateRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository


LOGGER = logging.getLogger(__name__)
JST_TIMEZONE = "Asia/Tokyo"


class StdoutSender:
    def send(self, message: str) -> None:
        print("----- notification -----")
        print(message)


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
        default=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
        help="Discord webhook URL. If omitted and --stdout is not set, notifications are printed to stdout.",
    )
    parser.add_argument("--stdout", action="store_true", help="Send notifications to stdout.")
    return parser.parse_args()


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
    if timezone_name != JST_TIMEZONE:
        raise ValueError(f"timezone_name must be fixed to {JST_TIMEZONE}.")
    if trade_date is not None:
        return normalize_trade_date(trade_date)
    tz = ZoneInfo(timezone_name)
    now = _parse_now_iso(now_iso)
    return now.astimezone(tz).date().isoformat()


def _resolve_sender(args: argparse.Namespace):
    if args.stdout:
        LOGGER.info("送信先: stdout")
        return StdoutSender()
    webhook_url = args.discord_webhook_url.strip()
    if webhook_url:
        LOGGER.info("送信先: Discord webhook")
        return DiscordNotifier(webhook_url)
    LOGGER.info("送信先: stdout (Discord webhook未設定)")
    return StdoutSender()


def _result_payload(result: PipelineResult) -> dict[str, int]:
    return {
        "processed": result.processed_tickers,
        "sent": result.sent_notifications,
        "skipped": result.skipped_notifications,
        "errors": result.errors,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    settings = load_settings()
    trade_date = resolve_trade_date(trade_date=args.trade_date, now_iso=args.now_iso, timezone_name=settings.timezone)
    now_iso = resolve_now_utc_iso(now_iso=args.now_iso)
    sender = _resolve_sender(args)

    client = _create_firestore_client(project_id=settings.firestore_project_id)
    watchlist_repo = FirestoreWatchlistRepository(client)
    daily_repo = FirestoreDailyMetricsRepository(client)
    medians_repo = FirestoreMetricMediansRepository(client)
    signal_repo = FirestoreSignalStateRepository(client)
    log_repo = FirestoreNotificationLogRepository(client)
    watchlist_items = watchlist_repo.list_all()

    LOGGER.info("日次ジョブ開始: trade_date=%s watchlist_items=%s", trade_date, len(watchlist_items))
    if not watchlist_items:
        LOGGER.warning("watchlist が0件のため、処理対象はありません。")

    result = run_daily_pipeline(
        watchlist_items=watchlist_items,
        market_data_source=create_default_market_data_source(),
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
            cooldown_hours=settings.cooldown_hours,
            now_iso=now_iso,
            execution_mode=NotificationExecutionMode.DAILY,
        ),
    )
    payload = _result_payload(result)
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

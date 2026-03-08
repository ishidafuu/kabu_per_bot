#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
import os
from zoneinfo import ZoneInfo

from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.jquants_v2 import JQuantsV2Client
from kabu_per_bot.pipeline import NotificationExecutionMode
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings, resolve_runtime_settings
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_global_settings_repository import FirestoreGlobalSettingsRepository
from kabu_per_bot.storage.firestore_notification_log_repository import FirestoreNotificationLogRepository
from kabu_per_bot.storage.firestore_price_bars_daily_repository import FirestorePriceBarsDailyRepository
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date
from kabu_per_bot.storage.firestore_technical_alert_rules_repository import FirestoreTechnicalAlertRulesRepository
from kabu_per_bot.storage.firestore_technical_alert_state_repository import FirestoreTechnicalAlertStateRepository
from kabu_per_bot.storage.firestore_technical_indicators_daily_repository import (
    FirestoreTechnicalIndicatorsDailyRepository,
)
from kabu_per_bot.storage.firestore_technical_sync_state_repository import FirestoreTechnicalSyncStateRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository
from kabu_per_bot.technical_job import run_technical_job, select_active_watchlist_items
from kabu_per_bot.technical_sync import DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS, DEFAULT_TECHNICAL_OVERLAP_DAYS


LOGGER = logging.getLogger(__name__)
JST_TIMEZONE = "Asia/Tokyo"
DISCORD_WEBHOOK_DEFAULT_ENV = "DISCORD_WEBHOOK_URL"
DISCORD_WEBHOOK_TECHNICAL_ENV = "DISCORD_WEBHOOK_URL_TECHNICAL"
DISCORD_WEBHOOK_DAILY_ENV = "DISCORD_WEBHOOK_URL_DAILY"
DISCORD_TECHNICAL_CHANNEL = "DISCORD_TECHNICAL"


class StdoutSender:
    def send(self, message: str) -> None:
        print("----- notification -----")
        print(message)


class NotificationLogBypassRepository:
    def list_recent(self, ticker: str, *, limit: int = 100):
        _ = ticker, limit
        return []

    def append(self, entry) -> None:
        _ = entry
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run technical daily sync/calc/alert job.")
    parser.add_argument("--to-date", default=None, help="Trade date (YYYY-MM-DD). Default: today(JST)")
    parser.add_argument(
        "--now-iso",
        default=None,
        help="Current time in ISO8601 with timezone (e.g. 2026-03-08T18:00:00+09:00). Default: now(UTC)",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma separated ticker list. Default: all active watchlist.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("JQUANTS_API_KEY", "").strip(),
        help="J-Quants API v2 key. Default: JQUANTS_API_KEY env.",
    )
    parser.add_argument(
        "--discord-webhook-url",
        default=_resolve_discord_webhook_default(DISCORD_WEBHOOK_TECHNICAL_ENV, DISCORD_WEBHOOK_DAILY_ENV),
        help=(
            "Discord webhook URL. Required unless --stdout is set. "
            f"Default: {DISCORD_WEBHOOK_TECHNICAL_ENV} "
            f"(fallback: {DISCORD_WEBHOOK_DAILY_ENV} -> {DISCORD_WEBHOOK_DEFAULT_ENV})."
        ),
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
        help="Use with --stdout for notification preview. Bypass cooldown and notification_log writes.",
    )
    parser.add_argument(
        "--skip-alerts",
        action="store_true",
        help="Run sync/calc only and skip Discord alert evaluation.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Ignore latest sync cursor and refetch from the initial lookback window.",
    )
    parser.add_argument(
        "--initial-lookback-days",
        type=int,
        default=DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS,
        help=f"Lookback days when ticker has no sync history (default: {DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--overlap-days",
        type=int,
        default=DEFAULT_TECHNICAL_OVERLAP_DAYS,
        help=f"Overlap days from latest fetched trade date (default: {DEFAULT_TECHNICAL_OVERLAP_DAYS}).",
    )
    return parser.parse_args()


def _resolve_discord_webhook_default(primary_env_key: str, *fallback_env_keys: str) -> str:
    for env_key in (primary_env_key, *fallback_env_keys):
        value = os.environ.get(env_key, "").strip()
        if value:
            return value
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
    return _parse_now_iso(now_iso).astimezone(timezone.utc).isoformat()


def resolve_trade_date(*, trade_date: str | None = None, now_iso: str | None = None, timezone_name: str) -> str:
    if trade_date is not None:
        return normalize_trade_date(trade_date)
    return _parse_now_iso(now_iso).astimezone(ZoneInfo(timezone_name)).date().isoformat()


def _resolve_sender(args: argparse.Namespace):
    if args.stdout:
        LOGGER.info("送信先: stdout")
        return StdoutSender()
    webhook_url = args.discord_webhook_url.strip()
    if not webhook_url:
        raise ValueError(
            "Discord webhook URL が必要です。"
            f"--discord-webhook-url または "
            f"{DISCORD_WEBHOOK_TECHNICAL_ENV}/{DISCORD_WEBHOOK_DAILY_ENV}/{DISCORD_WEBHOOK_DEFAULT_ENV} "
            "を設定してください。"
        )
    LOGGER.info("送信先: Discord webhook (channel=%s)", DISCORD_TECHNICAL_CHANNEL)
    return DiscordNotifier(webhook_url)


def _resolve_notification_log_repo(args: argparse.Namespace, base_repo: FirestoreNotificationLogRepository):
    if args.no_notification_log:
        if not args.stdout:
            raise ValueError("--no-notification-log は --stdout と併用してください。")
        LOGGER.info("通知ログ: バイパス（cooldown無効・notification_log未記録）")
        return NotificationLogBypassRepository()
    return base_repo


def _resolve_runtime_settings(*, settings, client):
    try:
        runtime_settings = resolve_runtime_settings(
            default_cooldown_hours=settings.cooldown_hours,
            global_settings=FirestoreGlobalSettingsRepository(client).get_global_settings(),
        )
        LOGGER.info(
            "クールダウン設定: %s時間 (source=%s)",
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


def _parse_target_tickers(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [normalize_ticker(row) for row in raw.split(",") if row.strip()]


def _resolve_execution_mode(raw: str) -> NotificationExecutionMode:
    mapping = {
        "all": NotificationExecutionMode.ALL,
        "daily": NotificationExecutionMode.DAILY,
        "at_21": NotificationExecutionMode.AT_21,
    }
    return mapping[raw]


def _resolve_job_recorded_at(*, now_iso: str | None) -> str:
    if now_iso is None:
        return datetime.now(timezone.utc).isoformat()
    return resolve_now_utc_iso(now_iso=now_iso)


def _run(
    *,
    job_name: str,
    force_full_refresh: bool,
    force_skip_alerts: bool,
) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    if not args.api_key.strip():
        raise ValueError("J-Quants API key が必要です。--api-key か JQUANTS_API_KEY を設定してください。")

    settings = load_settings()
    to_date = resolve_trade_date(trade_date=args.to_date, now_iso=args.now_iso, timezone_name=settings.timezone)
    now_iso = resolve_now_utc_iso(now_iso=args.now_iso)
    full_refresh = force_full_refresh or bool(args.full_refresh)
    alerts_enabled = not (force_skip_alerts or args.skip_alerts)
    notification_log_repo: FirestoreNotificationLogRepository | None = None
    job_started_at: str | None = None

    try:
        sender = _resolve_sender(args) if alerts_enabled else StdoutSender()
        client = _create_firestore_client(project_id=settings.firestore_project_id)
        runtime_settings = _resolve_runtime_settings(settings=settings, client=client)
        watchlist_repo = FirestoreWatchlistRepository(client)
        price_bars_repo = FirestorePriceBarsDailyRepository(client)
        indicators_repo = FirestoreTechnicalIndicatorsDailyRepository(client)
        sync_state_repo = FirestoreTechnicalSyncStateRepository(client)
        technical_alert_rules_repo = FirestoreTechnicalAlertRulesRepository(client)
        technical_alert_state_repo = FirestoreTechnicalAlertStateRepository(client)
        notification_log_repo = FirestoreNotificationLogRepository(client)
        alert_notification_repo = (
            _resolve_notification_log_repo(args, notification_log_repo)
            if alerts_enabled
            else NotificationLogBypassRepository()
        )
        jquants_client = JQuantsV2Client(api_key=args.api_key.strip())
        target_tickers = _parse_target_tickers(args.tickers)
        watchlist_items = select_active_watchlist_items(
            watchlist_repo.list_all(),
            target_tickers=target_tickers,
        )
        job_started_at = _resolve_job_recorded_at(now_iso=args.now_iso)

        LOGGER.info(
            "技術日次ジョブ開始: to_date=%s target_tickers=%s full_refresh=%s alerts_enabled=%s",
            to_date,
            len(watchlist_items),
            full_refresh,
            alerts_enabled,
        )
        if not watchlist_items:
            LOGGER.warning("watchlist が0件のため、処理対象はありません。")

        result = run_technical_job(
            watchlist_items=watchlist_items,
            to_date=to_date,
            jquants_client=jquants_client,
            price_bars_repo=price_bars_repo,
            indicators_repo=indicators_repo,
            sync_state_repo=sync_state_repo,
            technical_alert_rules_repo=technical_alert_rules_repo,
            technical_alert_state_repo=technical_alert_state_repo,
            notification_log_repo=alert_notification_repo,
            sender=sender,
            cooldown_hours=runtime_settings.cooldown_hours,
            now_iso=now_iso,
            channel=DISCORD_TECHNICAL_CHANNEL,
            execution_mode=_resolve_execution_mode(args.execution_mode),
            full_refresh=full_refresh,
            alerts_enabled=alerts_enabled,
            initial_lookback_days=args.initial_lookback_days,
            overlap_days=args.overlap_days,
        )
        payload = asdict(result)
        status = "FAILED" if result.errors > 0 else "SUCCESS"
    except Exception as exc:
        if notification_log_repo is not None:
            failed_started_at = job_started_at or _resolve_job_recorded_at(now_iso=None)
            try:
                notification_log_repo.append_job_run(
                    job_name=job_name,
                    started_at=failed_started_at,
                    finished_at=_resolve_job_recorded_at(now_iso=args.now_iso),
                    status="FAILED",
                    error_count=1,
                    detail=str(exc),
                )
            except Exception:
                LOGGER.exception("job_run の失敗記録保存にも失敗しました: job=%s", job_name)
        raise

    if notification_log_repo is None or job_started_at is None:
        raise RuntimeError("job_run 記録前に通知ログリポジトリの初期化に失敗しました。")
    notification_log_repo.append_job_run(
        job_name=job_name,
        started_at=job_started_at,
        finished_at=_resolve_job_recorded_at(now_iso=args.now_iso),
        status=status,
        error_count=result.errors,
        detail=json.dumps(payload, ensure_ascii=False),
    )
    print(json.dumps(payload, ensure_ascii=False))
    LOGGER.info(
        "技術日次ジョブ完了: processed=%s fetched=%s upserted=%s indicators=%s sent=%s skipped=%s errors=%s",
        result.processed_tickers,
        result.fetched_rows,
        result.upserted_rows,
        result.indicator_written_rows,
        result.sent_notifications,
        result.skipped_notifications,
        result.errors,
    )
    return 0 if result.errors == 0 else 1


def main() -> int:
    return _run(job_name="technical_daily", force_full_refresh=False, force_skip_alerts=False)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.exception("technical daily job failed: %s", exc)
        raise SystemExit(1) from exc

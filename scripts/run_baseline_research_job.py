#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from kabu_per_bot.baseline_research_service import DefaultBaselineResearchCollector, refresh_baseline_research
from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.market_data import create_default_market_data_source
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings, resolve_runtime_settings
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_baseline_research_repository import FirestoreBaselineResearchRepository
from kabu_per_bot.storage.firestore_global_settings_repository import FirestoreGlobalSettingsRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date


LOGGER = logging.getLogger(__name__)
JST_TIMEZONE = "Asia/Tokyo"
DISCORD_WEBHOOK_DEFAULT_ENV = "DISCORD_WEBHOOK_URL"
DISCORD_WEBHOOK_DAILY_ENV = "DISCORD_WEBHOOK_URL_DAILY"


class StdoutSender:
    def send(self, message: str) -> None:
        print("----- notification -----")
        print(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run monthly baseline research refresh.")
    parser.add_argument("--now-iso", default=None, help="Current time in ISO8601 with timezone.")
    parser.add_argument(
        "--trade-date",
        default=None,
        help="Trade date (YYYY-MM-DD). If omitted, now(JST) is used.",
    )
    parser.add_argument(
        "--tickers",
        nargs="*",
        default=(),
        help="Retry specific tickers only (e.g. 7203:TSE 6758:TSE).",
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
        "--stdout",
        action="store_true",
        help="Send notifications to stdout.",
    )
    parser.add_argument(
        "--jquants-api-key",
        default=os.environ.get("JQUANTS_API_KEY", "").strip(),
        help="J-Quants API key.",
    )
    parser.add_argument(
        "--ignore-baseline-schedule",
        action="store_true",
        help="Run even when current JST date/time does not match monthly schedule setting.",
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
    LOGGER.info("送信先: Discord webhook")
    return DiscordNotifier(webhook_url)


def _resolve_trade_date(*, trade_date: str | None, now_iso: str | None) -> str:
    if trade_date:
        return normalize_trade_date(trade_date)
    now = datetime.now(timezone.utc) if now_iso is None else datetime.fromisoformat(now_iso)
    if now.tzinfo is None:
        raise ValueError("now_iso must include timezone offset")
    return now.astimezone(ZoneInfo(JST_TIMEZONE)).date().isoformat()


def _resolve_as_of_month(*, trade_date: str) -> str:
    parsed = datetime.fromisoformat(f"{normalize_trade_date(trade_date)}T00:00:00+00:00")
    return parsed.strftime("%Y-%m")


def _resolve_runtime_baseline_scheduled_time(*, settings, client) -> str:
    try:
        repository = FirestoreGlobalSettingsRepository(client)
        runtime_settings = resolve_runtime_settings(
            default_cooldown_hours=settings.cooldown_hours,
            global_settings=repository.get_global_settings(),
        )
        return runtime_settings.baseline_monthly_scheduled_time
    except Exception as exc:
        LOGGER.warning("全体設定の取得に失敗したため環境変数設定を使用: %s", exc)
        return resolve_runtime_settings(
            default_cooldown_hours=settings.cooldown_hours,
            global_settings=GlobalRuntimeSettings(),
        ).baseline_monthly_scheduled_time


def _should_run_monthly_now(*, now_iso: str | None, scheduled_time: str) -> bool:
    now = datetime.now(timezone.utc) if now_iso is None else datetime.fromisoformat(now_iso)
    if now.tzinfo is None:
        raise ValueError("now_iso must include timezone offset")
    jst_now = now.astimezone(ZoneInfo(JST_TIMEZONE))
    return jst_now.day == 1 and jst_now.strftime("%H:%M") == scheduled_time


def _format_failure_message(
    *,
    failures,
) -> str:
    lines = ["【基礎調査更新失敗】月次更新で失敗が発生しました。"]
    for row in failures[:10]:
        last_success = row.last_success_at or "なし"
        lines.append(
            f"- {row.ticker} / source={row.source} / reason={row.reason} / last_success={last_success}"
        )
    lines.append("再取得: /ops の基礎調査更新ジョブを再実行、または CLI で --tickers 指定して再実行してください。")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    settings = load_settings()
    sender = _resolve_sender(args)
    trade_date = _resolve_trade_date(trade_date=args.trade_date, now_iso=args.now_iso)
    as_of_month = _resolve_as_of_month(trade_date=trade_date)

    client = _create_firestore_client(project_id=settings.firestore_project_id)
    scheduled_time = _resolve_runtime_baseline_scheduled_time(settings=settings, client=client)
    if not args.tickers and not getattr(args, "ignore_baseline_schedule", False):
        if not _should_run_monthly_now(now_iso=args.now_iso, scheduled_time=scheduled_time):
            payload = {"processed": 0, "updated": 0, "failed": 0}
            print(json.dumps(payload, ensure_ascii=False))
            LOGGER.info(
                "基礎調査更新を時刻条件でスキップ: scheduled=%s JST (毎月1日) trade_date=%s",
                scheduled_time,
                trade_date,
            )
            return 0

    watchlist_repo = FirestoreWatchlistRepository(client)
    baseline_repo = FirestoreBaselineResearchRepository(client)

    items = watchlist_repo.list_all()
    if args.tickers:
        targets = {normalize_ticker(ticker) for ticker in args.tickers}
        items = [row for row in items if row.ticker in targets]

    collector = DefaultBaselineResearchCollector(
        create_default_market_data_source(
            jquants_api_key=getattr(args, "jquants_api_key", ""),
        )
    )
    result = refresh_baseline_research(
        watchlist_items=items,
        collector=collector,
        repository=baseline_repo,
        as_of_month=as_of_month,
    )

    if result.failed_tickers > 0:
        sender.send(_format_failure_message(failures=result.failures))

    payload = {
        "processed": result.processed_tickers,
        "updated": result.updated_tickers,
        "failed": result.failed_tickers,
    }
    print(json.dumps(payload, ensure_ascii=False))
    LOGGER.info(
        "基礎調査更新完了: processed=%s updated=%s failed=%s",
        payload["processed"],
        payload["updated"],
        payload["failed"],
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.exception("baseline research job failed: %s", exc)
        raise SystemExit(1) from exc

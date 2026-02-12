#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os

from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.earnings_job import JST_TIMEZONE, run_earnings_job
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_earnings_calendar_repository import FirestoreEarningsCalendarRepository
from kabu_per_bot.storage.firestore_notification_log_repository import FirestoreNotificationLogRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository


LOGGER = logging.getLogger(__name__)


class StdoutSender:
    def send(self, message: str) -> None:
        print("----- notification -----")
        print(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run earnings notification job.")
    parser.add_argument("--job", required=True, choices=("weekly", "tomorrow"), help="Job type.")
    parser.add_argument(
        "--now-iso",
        default=None,
        help="Current time in ISO8601 with timezone (e.g. 2026-02-14T21:00:00+09:00). Default: now(UTC)",
    )
    parser.add_argument(
        "--discord-webhook-url",
        default=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
        help="Discord webhook URL. Required unless --stdout is set.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Send notifications to stdout instead of Discord webhook.",
    )
    return parser.parse_args()


def _create_firestore_client(*, project_id: str):
    try:
        from google.cloud import firestore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-cloud-firestore が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc
    return firestore.Client(project=project_id or None)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    settings = load_settings()

    if args.stdout:
        sender = StdoutSender()
        LOGGER.info("送信先: stdout")
    else:
        webhook_url = args.discord_webhook_url.strip()
        if not webhook_url:
            raise ValueError("Discord webhook URL が必要です。--discord-webhook-url か DISCORD_WEBHOOK_URL を設定してください。")
        sender = DiscordNotifier(webhook_url)
        LOGGER.info("送信先: Discord webhook")

    client = _create_firestore_client(project_id=settings.firestore_project_id)
    watchlist_repo = FirestoreWatchlistRepository(client)
    earnings_repo = FirestoreEarningsCalendarRepository(client)
    notification_log_repo = FirestoreNotificationLogRepository(client)

    result = run_earnings_job(
        job_type=args.job,
        watchlist_reader=watchlist_repo,
        earnings_reader=earnings_repo,
        notification_log_repo=notification_log_repo,
        sender=sender,
        cooldown_hours=settings.cooldown_hours,
        now_iso=args.now_iso,
        timezone_name=JST_TIMEZONE,
        channel="DISCORD",
    )
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.error("earnings job failed: %s", exc)
        raise SystemExit(1) from exc

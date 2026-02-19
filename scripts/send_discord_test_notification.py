#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from kabu_per_bot.discord_notifier import DiscordNotifier


DISCORD_WEBHOOK_DEFAULT_ENV = "DISCORD_WEBHOOK_URL"
DISCORD_WEBHOOK_OPS_ENV = "DISCORD_WEBHOOK_URL_OPS"


def _resolve_discord_webhook_default() -> str:
    primary = os.environ.get(DISCORD_WEBHOOK_OPS_ENV, "").strip()
    if primary:
        return primary
    return os.environ.get(DISCORD_WEBHOOK_DEFAULT_ENV, "").strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send test notification to Discord webhook.")
    parser.add_argument(
        "--webhook-url",
        default=_resolve_discord_webhook_default(),
        help=(
            "Discord webhook URL. "
            f"Default: {DISCORD_WEBHOOK_OPS_ENV} (fallback: {DISCORD_WEBHOOK_DEFAULT_ENV})."
        ),
    )
    parser.add_argument(
        "--message",
        default="kabu_per_bot 疎通確認メッセージ",
        help="Message body to send.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    webhook = (args.webhook_url or "").strip()
    if not webhook:
        print(
            "Discord webhook URL is required via --webhook-url or "
            f"{DISCORD_WEBHOOK_OPS_ENV}/{DISCORD_WEBHOOK_DEFAULT_ENV}.",
            file=sys.stderr,
        )
        return 2

    notifier = DiscordNotifier(webhook)
    notifier.send(args.message)
    print("Discord test notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

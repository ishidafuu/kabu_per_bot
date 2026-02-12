#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys

from kabu_per_bot.discord_notifier import DiscordNotifier


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send test notification to Discord webhook.")
    parser.add_argument(
        "--webhook-url",
        default=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
        help="Discord webhook URL. Default: DISCORD_WEBHOOK_URL env.",
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
        print("Discord webhook URL is required via --webhook-url or DISCORD_WEBHOOK_URL.", file=sys.stderr)
        return 2

    notifier = DiscordNotifier(webhook)
    notifier.send(args.message)
    print("Discord test notification sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

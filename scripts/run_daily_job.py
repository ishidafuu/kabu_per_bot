#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import argparse
import json
import logging
import os
import sys

from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.market_data import MarketDataSnapshot, MarketDataSource
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.pipeline import DailyPipelineConfig, run_daily_pipeline
from kabu_per_bot.signal import NotificationLogEntry, SignalState
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


LOGGER = logging.getLogger(__name__)


class DemoMarketDataSource(MarketDataSource):
    @property
    def source_name(self) -> str:
        return "demo"

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        return MarketDataSnapshot.create(
            ticker=ticker,
            close_price=100.0,
            eps_forecast=10.0,
            sales_forecast=100.0,
            source=self.source_name,
            earnings_date="2026-05-10",
        )


@dataclass
class InMemoryDailyMetricsRepo:
    rows: list[DailyMetric] = field(default_factory=list)

    def upsert(self, metric: DailyMetric) -> None:
        self.rows = [row for row in self.rows if not (row.ticker == metric.ticker and row.trade_date == metric.trade_date)]
        self.rows.append(metric)

    def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
        rows = [row for row in self.rows if row.ticker == ticker]
        rows.sort(key=lambda row: row.trade_date, reverse=True)
        return rows[:limit]


@dataclass
class InMemoryMediansRepo:
    rows: list[MetricMedians] = field(default_factory=list)

    def upsert(self, medians: MetricMedians) -> None:
        self.rows.append(medians)


@dataclass
class InMemorySignalStateRepo:
    rows: list[SignalState] = field(default_factory=list)

    def upsert(self, state: SignalState) -> None:
        self.rows = [row for row in self.rows if not (row.ticker == state.ticker and row.trade_date == state.trade_date)]
        self.rows.append(state)

    def get_latest(self, ticker: str) -> SignalState | None:
        rows = [row for row in self.rows if row.ticker == ticker]
        rows.sort(key=lambda row: row.trade_date, reverse=True)
        return rows[0] if rows else None


@dataclass
class InMemoryNotificationLogRepo:
    rows: list[NotificationLogEntry] = field(default_factory=list)

    def append(self, entry: NotificationLogEntry) -> None:
        self.rows.append(entry)

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        rows = [row for row in self.rows if row.ticker == ticker]
        rows.sort(key=lambda row: row.sent_at, reverse=True)
        return rows[:limit]


class StdoutSender:
    def send(self, message: str) -> None:
        print("----- notification -----")
        print(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MVP daily pipeline in local demo mode.")
    parser.add_argument("--trade-date", default=date.today().isoformat(), help="Trade date (YYYY-MM-DD)")
    parser.add_argument("--now-iso", default=None, help="Current time in ISO8601. Default: now(UTC)")
    parser.add_argument(
        "--discord-webhook-url",
        default=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
        help="Discord webhook URL. If empty, notifications are printed to stdout.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    now_iso = args.now_iso or datetime.now(timezone.utc).isoformat()

    watchlist_items = [
        WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
    ]

    daily_repo = InMemoryDailyMetricsRepo(
        rows=[
            DailyMetric(
                ticker="3901:TSE",
                trade_date="2026-02-11",
                close_price=150.0,
                eps_forecast=10.0,
                sales_forecast=100.0,
                per_value=15.0,
                psr_value=1.5,
                data_source="demo",
                fetched_at=now_iso,
            )
        ]
    )
    medians_repo = InMemoryMediansRepo()
    signal_repo = InMemorySignalStateRepo()
    log_repo = InMemoryNotificationLogRepo()
    sender = DiscordNotifier(args.discord_webhook_url) if args.discord_webhook_url else StdoutSender()

    result = run_daily_pipeline(
        watchlist_items=watchlist_items,
        market_data_source=DemoMarketDataSource(),
        daily_metrics_repo=daily_repo,
        medians_repo=medians_repo,
        signal_state_repo=signal_repo,
        notification_log_repo=log_repo,
        sender=sender,
        config=DailyPipelineConfig(
            trade_date=args.trade_date,
            window_1w_days=2,
            window_3m_days=2,
            window_1y_days=2,
            cooldown_hours=2,
            now_iso=now_iso,
        ),
    )
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.error("daily job failed: %s", exc)
        raise SystemExit(1) from exc

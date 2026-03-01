from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import unittest

from kabu_per_bot.holdings_phase_a import PhaseAHoldingsConfig, run_holdings_phase_a_pipeline
from kabu_per_bot.market_data import MarketDataSnapshot
from kabu_per_bot.metrics import DailyMetric
from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchPriority, WatchlistItem


@dataclass
class InMemoryDailyMetricsRepo:
    rows: list[DailyMetric] = field(default_factory=list)

    def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
        filtered = [row for row in self.rows if row.ticker == ticker]
        filtered.sort(key=lambda row: row.trade_date, reverse=True)
        return filtered[:limit]


@dataclass
class InMemoryNotificationLogRepo:
    rows: list[NotificationLogEntry] = field(default_factory=list)

    def append(self, entry: NotificationLogEntry) -> None:
        self.rows.append(entry)

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        filtered = [row for row in self.rows if row.ticker == ticker]
        filtered.sort(key=lambda row: row.sent_at, reverse=True)
        return filtered[:limit]


@dataclass
class SpySender:
    messages: list[str] = field(default_factory=list)

    def send(self, message: str) -> None:
        self.messages.append(message)


@dataclass
class FailOnceSender:
    messages: list[str] = field(default_factory=list)
    failed: bool = False

    def send(self, message: str) -> None:
        if not self.failed:
            self.failed = True
            raise RuntimeError("send failed")
        self.messages.append(message)


@dataclass
class StaticMarketDataSource:
    snapshots: dict[str, MarketDataSnapshot]

    @property
    def source_name(self) -> str:
        return "fake"

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        return self.snapshots[ticker]


def _watch_item(*, ticker: str, priority: WatchPriority) -> WatchlistItem:
    return WatchlistItem(
        ticker=ticker,
        name=f"{ticker}株式会社",
        metric_type=MetricType.PER,
        notify_channel=NotifyChannel.DISCORD,
        notify_timing=NotifyTiming.IMMEDIATE,
        priority=priority,
        always_notify_enabled=False,
        is_active=True,
    )


def _daily_rows(*, ticker: str, closes: list[float], start_date: str = "2026-02-20") -> list[DailyMetric]:
    base = date.fromisoformat(start_date)
    rows: list[DailyMetric] = []
    for offset, close in enumerate(closes):
        trade_date = (base - timedelta(days=offset)).isoformat()
        rows.append(
            DailyMetric(
                ticker=ticker,
                trade_date=trade_date,
                close_price=close,
                eps_forecast=10.0,
                sales_forecast=100.0,
                per_value=close / 10.0,
                psr_value=1.0,
                data_source="株探",
                fetched_at="2026-02-20T10:00:00+00:00",
            )
        )
    return rows


class HoldingsPhaseAPipelineTest(unittest.TestCase):
    def test_phase_a_sends_core_always_and_satellite_on_exception(self) -> None:
        watchlist_items = [
            _watch_item(ticker="1111:TSE", priority=WatchPriority.HIGH),
            _watch_item(ticker="2222:TSE", priority=WatchPriority.MEDIUM),
            _watch_item(ticker="3333:TSE", priority=WatchPriority.LOW),
        ]
        daily_repo = InMemoryDailyMetricsRepo(
            rows=(
                _daily_rows(ticker="1111:TSE", closes=[100.0, 99.0, 98.0, 97.0, 96.0, 95.0])
                + _daily_rows(ticker="2222:TSE", closes=[100.0, 90.0, 89.0, 88.0, 87.0, 86.0])
                + _daily_rows(ticker="3333:TSE", closes=[100.0, 99.0, 99.0, 99.0, 99.0, 99.0])
            )
        )
        market_source = StaticMarketDataSource(
            snapshots={
                "1111:TSE": MarketDataSnapshot.create(
                    ticker="1111:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    earnings_date="2026-03-25",
                    source="株探",
                ),
                "2222:TSE": MarketDataSnapshot.create(
                    ticker="2222:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    earnings_date="2026-02-27",
                    source="株探",
                ),
                "3333:TSE": MarketDataSnapshot.create(
                    ticker="3333:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    earnings_date="2026-03-30",
                    source="株探",
                ),
            }
        )
        sender = SpySender()
        log_repo = InMemoryNotificationLogRepo()
        config = PhaseAHoldingsConfig(
            trade_date="2026-02-20",
            now_iso="2026-02-20T12:00:00+00:00",
            cooldown_hours=2,
        )

        result = run_holdings_phase_a_pipeline(
            watchlist_items=watchlist_items,
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=config,
        )

        self.assertEqual(result.processed_tickers, 3)
        self.assertEqual(result.sent_notifications, 2)
        self.assertEqual(result.skipped_notifications, 0)
        self.assertEqual(len(sender.messages), 2)
        self.assertTrue(any("CORE 1111:TSE" in message for message in sender.messages))
        self.assertTrue(any("SATELLITE 2222:TSE" in message for message in sender.messages))
        self.assertTrue(any("RL2" in message for message in sender.messages))
        self.assertEqual(len(log_repo.rows), 2)

    def test_phase_a_respects_cooldown_on_rerun(self) -> None:
        watchlist_items = [_watch_item(ticker="1111:TSE", priority=WatchPriority.HIGH)]
        daily_repo = InMemoryDailyMetricsRepo(rows=_daily_rows(ticker="1111:TSE", closes=[100.0, 99.0, 98.0, 97.0, 96.0, 95.0]))
        market_source = StaticMarketDataSource(
            snapshots={
                "1111:TSE": MarketDataSnapshot.create(
                    ticker="1111:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    earnings_date="2026-03-20",
                    source="株探",
                )
            }
        )
        sender = SpySender()
        log_repo = InMemoryNotificationLogRepo()
        config = PhaseAHoldingsConfig(
            trade_date="2026-02-20",
            now_iso="2026-02-20T12:00:00+00:00",
            cooldown_hours=2,
        )

        first = run_holdings_phase_a_pipeline(
            watchlist_items=watchlist_items,
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=config,
        )
        second = run_holdings_phase_a_pipeline(
            watchlist_items=watchlist_items,
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=config,
        )

        self.assertEqual(first.sent_notifications, 1)
        self.assertEqual(second.sent_notifications, 0)
        self.assertEqual(second.skipped_notifications, 1)
        self.assertEqual(len(sender.messages), 1)

    def test_phase_a_continues_when_one_notification_send_fails(self) -> None:
        watchlist_items = [
            _watch_item(ticker="1111:TSE", priority=WatchPriority.HIGH),
            _watch_item(ticker="2222:TSE", priority=WatchPriority.MEDIUM),
        ]
        daily_repo = InMemoryDailyMetricsRepo(
            rows=(
                _daily_rows(ticker="1111:TSE", closes=[100.0, 99.0, 98.0, 97.0, 96.0, 95.0])
                + _daily_rows(ticker="2222:TSE", closes=[100.0, 90.0, 89.0, 88.0, 87.0, 86.0])
            )
        )
        market_source = StaticMarketDataSource(
            snapshots={
                "1111:TSE": MarketDataSnapshot.create(
                    ticker="1111:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    earnings_date="2026-03-20",
                    source="株探",
                ),
                "2222:TSE": MarketDataSnapshot.create(
                    ticker="2222:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    earnings_date="2026-02-27",
                    source="株探",
                ),
            }
        )
        sender = FailOnceSender()
        log_repo = InMemoryNotificationLogRepo()
        config = PhaseAHoldingsConfig(
            trade_date="2026-02-20",
            now_iso="2026-02-20T12:00:00+00:00",
            cooldown_hours=2,
        )

        result = run_holdings_phase_a_pipeline(
            watchlist_items=watchlist_items,
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=config,
        )

        self.assertEqual(result.processed_tickers, 2)
        self.assertEqual(result.errors, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertEqual(len(log_repo.rows), 1)


if __name__ == "__main__":
    unittest.main()

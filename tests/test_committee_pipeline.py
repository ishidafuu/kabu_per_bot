from __future__ import annotations

import unittest

from kabu_per_bot.committee_pipeline import CommitteePipelineConfig, run_committee_pipeline
from kabu_per_bot.market_data import MarketDataSnapshot
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.watchlist import (
    EvaluationNotifyMode,
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchlistItem,
)


class FakeMarketDataSource:
    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        return MarketDataSnapshot.create(
            ticker=ticker,
            close_price=100.0,
            eps_forecast=10.0,
            sales_forecast=100.0,
            earnings_date="2026-03-20",
            source="株探",
            fetched_at="2026-03-01T09:00:00+00:00",
        )


class FakeDailyMetricsRepo:
    def __init__(self) -> None:
        self._rows = [
            DailyMetric(
                ticker="3901:TSE",
                trade_date="2026-03-01",
                close_price=100.0,
                eps_forecast=10.0,
                sales_forecast=100.0,
                per_value=10.0,
                psr_value=1.0,
                data_source="株探",
                fetched_at="2026-03-01T09:00:00+00:00",
            ),
            DailyMetric(
                ticker="3901:TSE",
                trade_date="2026-02-28",
                close_price=98.0,
                eps_forecast=10.0,
                sales_forecast=100.0,
                per_value=9.8,
                psr_value=1.0,
                data_source="株探",
                fetched_at="2026-02-28T09:00:00+00:00",
            ),
            DailyMetric(
                ticker="3901:TSE",
                trade_date="2026-02-24",
                close_price=94.0,
                eps_forecast=10.0,
                sales_forecast=100.0,
                per_value=9.4,
                psr_value=1.0,
                data_source="株探",
                fetched_at="2026-02-24T09:00:00+00:00",
            ),
        ]

    def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
        return self._rows[:limit]


class FakeMediansRepo:
    def list_recent(self, ticker: str, *, limit: int) -> list[MetricMedians]:
        return [
            MetricMedians(
                ticker=ticker,
                trade_date="2026-03-01",
                median_1w=11.0,
                median_3m=12.0,
                median_1y=13.0,
                source_metric_type=MetricType.PER,
                calculated_at="2026-03-01T09:00:00+00:00",
            )
        ][:limit]


class FakeNotificationLogRepo:
    def __init__(self) -> None:
        self.rows: list[NotificationLogEntry] = []

    def append(self, entry: NotificationLogEntry) -> None:
        self.rows.append(entry)

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        return [row for row in self.rows if row.ticker == ticker][:limit]


class FakeSender:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, message: str) -> None:
        self.messages.append(message)


class CommitteePipelineTest(unittest.TestCase):
    def test_run_committee_pipeline_sends_for_enabled_ticker(self) -> None:
        watchlist_items = [
            WatchlistItem(
                ticker="3901:TSE",
                name="富士フイルム",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.IMMEDIATE,
                evaluation_enabled=True,
                evaluation_notify_mode=EvaluationNotifyMode.ALL,
            )
        ]
        sender = FakeSender()
        log_repo = FakeNotificationLogRepo()
        result = run_committee_pipeline(
            watchlist_items=watchlist_items,
            market_data_source=FakeMarketDataSource(),
            daily_metrics_repo=FakeDailyMetricsRepo(),
            medians_repo=FakeMediansRepo(),
            notification_log_repo=log_repo,
            sender=sender,
            config=CommitteePipelineConfig(
                trade_date="2026-03-01",
                now_iso="2026-03-01T09:00:00+00:00",
                cooldown_hours=2,
            ),
        )
        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertEqual(len(log_repo.rows), 1)
        self.assertEqual(log_repo.rows[0].category, "委員会評価")
        self.assertIsNotNone(log_repo.rows[0].evaluation_confidence)
        self.assertIsNotNone(log_repo.rows[0].evaluation_strength)

    def test_run_committee_pipeline_respects_alert_only_threshold(self) -> None:
        watchlist_items = [
            WatchlistItem(
                ticker="3901:TSE",
                name="富士フイルム",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.IMMEDIATE,
                evaluation_enabled=True,
                evaluation_notify_mode=EvaluationNotifyMode.ALERT_ONLY,
                evaluation_min_strength=5,
            )
        ]
        sender = FakeSender()
        result = run_committee_pipeline(
            watchlist_items=watchlist_items,
            market_data_source=FakeMarketDataSource(),
            daily_metrics_repo=FakeDailyMetricsRepo(),
            medians_repo=FakeMediansRepo(),
            notification_log_repo=FakeNotificationLogRepo(),
            sender=sender,
            config=CommitteePipelineConfig(
                trade_date="2026-03-01",
                now_iso="2026-03-01T09:00:00+00:00",
                cooldown_hours=2,
            ),
        )
        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 0)
        self.assertEqual(result.skipped_notifications, 1)
        self.assertEqual(len(sender.messages), 0)


if __name__ == "__main__":
    unittest.main()

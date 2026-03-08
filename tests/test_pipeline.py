from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.earnings import EarningsCalendarEntry
from kabu_per_bot.market_data import MarketDataFetchError, MarketDataSnapshot
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.pipeline import (
    DailyPipelineConfig,
    NotificationExecutionMode,
    run_daily_pipeline,
    run_tomorrow_earnings_pipeline,
    run_weekly_earnings_pipeline,
)
from kabu_per_bot.signal import NotificationLogEntry, SignalState
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


@dataclass
class FakeMarketDataSource:
    snapshots: dict[str, MarketDataSnapshot]
    failures: dict[str, str] = field(default_factory=dict)

    @property
    def source_name(self) -> str:
        return "fake"

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        if ticker in self.failures:
            raise MarketDataFetchError(source="fake", ticker=ticker, reason=self.failures[ticker])
        return self.snapshots[ticker]


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


def _watch_item(ticker: str, name: str, *, always_notify_enabled: bool = False) -> WatchlistItem:
    return WatchlistItem(
        ticker=ticker,
        name=name,
        metric_type=MetricType.PER,
        notify_channel=NotifyChannel.DISCORD,
        notify_timing=NotifyTiming.IMMEDIATE,
        always_notify_enabled=always_notify_enabled,
    )


def _earnings_entry(ticker: str, earnings_date: str) -> EarningsCalendarEntry:
    return EarningsCalendarEntry(
        ticker=ticker,
        earnings_date=earnings_date,
        earnings_time="15:00",
        quarter="3Q",
        source="株探",
        fetched_at="2026-02-12T00:00:00+00:00",
    )


class PipelineTest(unittest.TestCase):
    def test_daily_pipeline_sends_signal_notification(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            }
        )
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
                    data_source="株探",
                    fetched_at="2026-02-11T00:00:00+00:00",
                )
            ]
        )
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[_watch_item("3901:TSE", "富士フイルム")],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("🔥 優先度:高 / 推奨:優先確認 / 判断:判定=1Y 3M 1W under / 新規", sender.messages[0])
        self.assertIn("1Y・3M・1Wの中央値を下回り。1日連続。決算まで87日。", sender.messages[0])
        self.assertIn("詳細: PER 10.00", sender.messages[0])
        self.assertEqual(len(log_repo.rows), 1)
        self.assertEqual(log_repo.rows[0].data_source, "株探")
        self.assertIsNotNone(log_repo.rows[0].data_fetched_at)

    def test_daily_pipeline_marks_signal_as_continuing_when_streak_extends(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            }
        )
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
                    data_source="株探",
                    fetched_at="2026-02-11T00:00:00+00:00",
                )
            ]
        )
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo(
            rows=[
                SignalState(
                    ticker="3901:TSE",
                    trade_date="2026-02-11",
                    metric_type=MetricType.PER,
                    metric_value=9.0,
                    under_1w=True,
                    under_3m=True,
                    under_1y=True,
                    combo="1Y+3M+1W",
                    is_strong=True,
                    category="超PER割安",
                    streak_days=3,
                    updated_at="2026-02-11T00:00:00+00:00",
                )
            ]
        )
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[_watch_item("3901:TSE", "富士フイルム")],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("🔥 優先度:高 / 推奨:優先確認 / 判断:判定=1Y 3M 1W under / 継続", sender.messages[0])
        self.assertIn("1Y・3M・1Wの中央値を下回り。4日連続。", sender.messages[0])

    def test_daily_pipeline_sends_status_notification_when_always_notify_enabled(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            }
        )
        daily_repo = InMemoryDailyMetricsRepo(
            rows=[
                DailyMetric(
                    ticker="3901:TSE",
                    trade_date="2026-02-11",
                    close_price=80.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    per_value=8.0,
                    psr_value=0.8,
                    data_source="株探",
                    fetched_at="2026-02-11T00:00:00+00:00",
                )
            ]
        )
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[_watch_item("3901:TSE", "富士フイルム", always_notify_enabled=True)],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("📘 優先度:低 / 推奨:様子見 / 判断:判定=下回りなし", sender.messages[0])
        self.assertIn("割安シグナルなし。", sender.messages[0])
        self.assertIn("詳細: PER 10.00", sender.messages[0])

    def test_daily_pipeline_marks_status_as_released_when_signal_clears(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=120.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            }
        )
        daily_repo = InMemoryDailyMetricsRepo(
            rows=[
                DailyMetric(
                    ticker="3901:TSE",
                    trade_date="2026-02-11",
                    close_price=80.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    per_value=8.0,
                    psr_value=0.8,
                    data_source="株探",
                    fetched_at="2026-02-11T00:00:00+00:00",
                )
            ]
        )
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo(
            rows=[
                SignalState(
                    ticker="3901:TSE",
                    trade_date="2026-02-11",
                    metric_type=MetricType.PER,
                    metric_value=8.0,
                    under_1w=True,
                    under_3m=True,
                    under_1y=True,
                    combo="1Y+3M+1W",
                    is_strong=True,
                    category="超PER割安",
                    streak_days=2,
                    updated_at="2026-02-11T00:00:00+00:00",
                )
            ]
        )
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[_watch_item("3901:TSE", "富士フイルム", always_notify_enabled=True)],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("📘 優先度:中 / 推奨:通常監視へ移行 / 判断:判定=解除", sender.messages[0])
        self.assertIn("割安シグナルは解消。", sender.messages[0])

    def test_daily_pipeline_does_not_mark_release_when_previous_signal_is_stale(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=120.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            }
        )
        daily_repo = InMemoryDailyMetricsRepo(
            rows=[
                DailyMetric(
                    ticker="3901:TSE",
                    trade_date="2026-02-11",
                    close_price=80.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    per_value=8.0,
                    psr_value=0.8,
                    data_source="株探",
                    fetched_at="2026-02-11T00:00:00+00:00",
                )
            ]
        )
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo(
            rows=[
                SignalState(
                    ticker="3901:TSE",
                    trade_date="2026-02-07",
                    metric_type=MetricType.PER,
                    metric_value=8.0,
                    under_1w=True,
                    under_3m=True,
                    under_1y=True,
                    combo="1Y+3M+1W",
                    is_strong=True,
                    category="超PER割安",
                    streak_days=2,
                    updated_at="2026-02-07T00:00:00+00:00",
                )
            ]
        )
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[_watch_item("3901:TSE", "富士フイルム", always_notify_enabled=True)],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("📘 優先度:低 / 推奨:様子見 / 判断:判定=下回りなし", sender.messages[0])
        self.assertIn("割安シグナルなし。", sender.messages[0])
        self.assertNotIn("シグナル種別:解除", sender.messages[0])

    def test_daily_pipeline_sends_insufficient_status_when_medians_missing(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            }
        )
        daily_repo = InMemoryDailyMetricsRepo()
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[_watch_item("3901:TSE", "富士フイルム", always_notify_enabled=True)],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn(
            "📘 優先度:中 / 推奨:データ確認 / 判断:判定=中央値不足(1W/3M/1Y)",
            sender.messages[0],
        )
        self.assertIn("中央値不足のため判定保留。", sender.messages[0])
        self.assertNotIn("シグナル種別: 解除", sender.messages[0])

    def test_daily_pipeline_daily_mode_sends_immediate_only(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=None,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                ),
                "3902:TSE": MarketDataSnapshot.create(
                    ticker="3902:TSE",
                    close_price=100.0,
                    eps_forecast=None,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                ),
            }
        )
        daily_repo = InMemoryDailyMetricsRepo()
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[
                WatchlistItem(
                    ticker="3901:TSE",
                    name="A",
                    metric_type=MetricType.PER,
                    notify_channel=NotifyChannel.DISCORD,
                    notify_timing=NotifyTiming.IMMEDIATE,
                ),
                WatchlistItem(
                    ticker="3902:TSE",
                    name="B",
                    metric_type=MetricType.PER,
                    notify_channel=NotifyChannel.DISCORD,
                    notify_timing=NotifyTiming.AT_21,
                ),
            ],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
                execution_mode=NotificationExecutionMode.DAILY,
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("3901:TSE", sender.messages[0])
        self.assertNotIn("3902:TSE", sender.messages[0])

    def test_daily_pipeline_at21_mode_sends_at21_only(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=None,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                ),
                "3902:TSE": MarketDataSnapshot.create(
                    ticker="3902:TSE",
                    close_price=100.0,
                    eps_forecast=None,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                ),
            }
        )
        daily_repo = InMemoryDailyMetricsRepo()
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[
                WatchlistItem(
                    ticker="3901:TSE",
                    name="A",
                    metric_type=MetricType.PER,
                    notify_channel=NotifyChannel.DISCORD,
                    notify_timing=NotifyTiming.IMMEDIATE,
                ),
                WatchlistItem(
                    ticker="3902:TSE",
                    name="B",
                    metric_type=MetricType.PER,
                    notify_channel=NotifyChannel.DISCORD,
                    notify_timing=NotifyTiming.AT_21,
                ),
            ],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
                execution_mode=NotificationExecutionMode.AT_21,
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("3902:TSE", sender.messages[0])
        self.assertNotIn("3901:TSE", sender.messages[0])

    def test_daily_pipeline_default_mode_keeps_backward_compatibility(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=None,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            }
        )
        daily_repo = InMemoryDailyMetricsRepo()
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[
                WatchlistItem(
                    ticker="3901:TSE",
                    name="A",
                    metric_type=MetricType.PER,
                    notify_channel=NotifyChannel.DISCORD,
                    notify_timing=NotifyTiming.AT_21,
                )
            ],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("3901:TSE", sender.messages[0])

    def test_daily_pipeline_allows_discord_variant_channel(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=None,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            }
        )
        daily_repo = InMemoryDailyMetricsRepo()
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[_watch_item("3901:TSE", "A")],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
                channel="DISCORD_DAILY",
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("【データ不明】", sender.messages[0])

    def test_daily_pipeline_continues_on_failure(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3902:TSE": MarketDataSnapshot.create(
                    ticker="3902:TSE",
                    close_price=100.0,
                    eps_forecast=None,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            },
            failures={"3901:TSE": "timeout"},
        )
        daily_repo = InMemoryDailyMetricsRepo()
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[
                _watch_item("3901:TSE", "A"),
                _watch_item("3902:TSE", "B"),
            ],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )
        self.assertEqual(result.processed_tickers, 2)
        self.assertEqual(result.errors, 1)
        self.assertEqual(result.sent_notifications, 2)
        self.assertEqual(len(sender.messages), 2)
        self.assertTrue(all("【データ不明】" in message for message in sender.messages))

    def test_daily_pipeline_skips_off_channel(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                )
            }
        )
        daily_repo = InMemoryDailyMetricsRepo()
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        watch_item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.OFF,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
        result = run_daily_pipeline(
            watchlist_items=[watch_item],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )
        self.assertEqual(result.processed_tickers, 0)
        self.assertEqual(result.sent_notifications, 0)
        self.assertEqual(len(sender.messages), 0)

    def test_daily_pipeline_continues_when_sender_fails(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                ),
                "3902:TSE": MarketDataSnapshot.create(
                    ticker="3902:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date="2026-05-10",
                ),
            }
        )
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
                    data_source="株探",
                    fetched_at="2026-02-11T00:00:00+00:00",
                ),
                DailyMetric(
                    ticker="3902:TSE",
                    trade_date="2026-02-11",
                    close_price=150.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    per_value=15.0,
                    psr_value=1.5,
                    data_source="株探",
                    fetched_at="2026-02-11T00:00:00+00:00",
                ),
            ]
        )
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = FailOnceSender()

        result = run_daily_pipeline(
            watchlist_items=[
                _watch_item("3901:TSE", "A"),
                _watch_item("3902:TSE", "B"),
            ],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )
        self.assertEqual(result.processed_tickers, 2)
        self.assertEqual(result.errors, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)

    def test_daily_pipeline_sends_data_unknown_when_earnings_date_missing(self) -> None:
        market_source = FakeMarketDataSource(
            snapshots={
                "3901:TSE": MarketDataSnapshot.create(
                    ticker="3901:TSE",
                    close_price=100.0,
                    eps_forecast=10.0,
                    sales_forecast=100.0,
                    source="株探",
                    earnings_date=None,
                )
            }
        )
        daily_repo = InMemoryDailyMetricsRepo()
        medians_repo = InMemoryMediansRepo()
        signal_repo = InMemorySignalStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_daily_pipeline(
            watchlist_items=[_watch_item("3901:TSE", "富士フイルム")],
            market_data_source=market_source,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=DailyPipelineConfig(
                trade_date="2026-02-12",
                window_1w_days=2,
                window_3m_days=2,
                window_1y_days=2,
                cooldown_hours=2,
                now_iso="2026-02-12T09:00:00+00:00",
            ),
        )
        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertIn("【データ不明】", sender.messages[0])
        self.assertIn("決算日時", sender.messages[0])

    def test_weekly_earnings_pipeline_notifies_watch_targets_only(self) -> None:
        watchlist_items = [
            WatchlistItem(
                ticker="3901:TSE",
                name="A",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.AT_21,
            ),
            WatchlistItem(
                ticker="3902:TSE",
                name="B",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.OFF,
                notify_timing=NotifyTiming.AT_21,
            ),
            WatchlistItem(
                ticker="3903:TSE",
                name="C",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.OFF,
            ),
            WatchlistItem(
                ticker="3904:TSE",
                name="D",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.AT_21,
                is_active=False,
            ),
        ]
        entries = [
            _earnings_entry("3901:TSE", "2026-02-16"),
            _earnings_entry("3902:TSE", "2026-02-16"),
            _earnings_entry("3903:TSE", "2026-02-16"),
            _earnings_entry("3904:TSE", "2026-02-16"),
            _earnings_entry("3999:TSE", "2026-02-16"),
        ]
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_weekly_earnings_pipeline(
            today="2026-02-14",
            watchlist_items=watchlist_items,
            earnings_entries=entries,
            notification_log_repo=log_repo,
            sender=sender,
            cooldown_hours=2,
            now_iso="2026-02-14T12:00:00+00:00",
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("【今週3Q決算】", sender.messages[0])
        self.assertIn("3901:TSE", sender.messages[0])
        self.assertEqual(len(log_repo.rows), 1)
        self.assertEqual(log_repo.rows[0].category, "今週決算")
        self.assertEqual(log_repo.rows[0].data_source, "株探")
        self.assertEqual(log_repo.rows[0].data_fetched_at, "2026-02-12T00:00:00+00:00")

    def test_weekly_earnings_pipeline_daily_mode_sends_immediate_only(self) -> None:
        watchlist_items = [
            WatchlistItem(
                ticker="3901:TSE",
                name="A",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.IMMEDIATE,
            ),
            WatchlistItem(
                ticker="3902:TSE",
                name="B",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.AT_21,
            ),
            WatchlistItem(
                ticker="3903:TSE",
                name="C",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.OFF,
            ),
        ]
        entries = [
            _earnings_entry("3901:TSE", "2026-02-16"),
            _earnings_entry("3902:TSE", "2026-02-16"),
            _earnings_entry("3903:TSE", "2026-02-16"),
        ]
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_weekly_earnings_pipeline(
            today="2026-02-14",
            watchlist_items=watchlist_items,
            earnings_entries=entries,
            notification_log_repo=log_repo,
            sender=sender,
            cooldown_hours=2,
            now_iso="2026-02-14T12:00:00+00:00",
            execution_mode=NotificationExecutionMode.DAILY,
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("3901:TSE", sender.messages[0])
        self.assertNotIn("3902:TSE", sender.messages[0])
        self.assertNotIn("3903:TSE", sender.messages[0])

    def test_weekly_earnings_pipeline_at21_mode_sends_at21_only(self) -> None:
        watchlist_items = [
            WatchlistItem(
                ticker="3901:TSE",
                name="A",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.IMMEDIATE,
            ),
            WatchlistItem(
                ticker="3902:TSE",
                name="B",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.AT_21,
            ),
            WatchlistItem(
                ticker="3903:TSE",
                name="C",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.OFF,
            ),
        ]
        entries = [
            _earnings_entry("3901:TSE", "2026-02-16"),
            _earnings_entry("3902:TSE", "2026-02-16"),
            _earnings_entry("3903:TSE", "2026-02-16"),
        ]
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_weekly_earnings_pipeline(
            today="2026-02-14",
            watchlist_items=watchlist_items,
            earnings_entries=entries,
            notification_log_repo=log_repo,
            sender=sender,
            cooldown_hours=2,
            now_iso="2026-02-14T12:00:00+00:00",
            execution_mode=NotificationExecutionMode.AT_21,
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("3902:TSE", sender.messages[0])
        self.assertNotIn("3901:TSE", sender.messages[0])
        self.assertNotIn("3903:TSE", sender.messages[0])

    def test_tomorrow_earnings_pipeline_sets_category_and_applies_cooldown(self) -> None:
        watchlist_items = [_watch_item("3901:TSE", "富士フイルム")]
        entries = [_earnings_entry("3901:TSE", "2026-02-13")]
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        first = run_tomorrow_earnings_pipeline(
            today="2026-02-12",
            watchlist_items=watchlist_items,
            earnings_entries=entries,
            notification_log_repo=log_repo,
            sender=sender,
            cooldown_hours=2,
            now_iso="2026-02-12T12:00:00+00:00",
        )
        second = run_tomorrow_earnings_pipeline(
            today="2026-02-12",
            watchlist_items=watchlist_items,
            earnings_entries=entries,
            notification_log_repo=log_repo,
            sender=sender,
            cooldown_hours=2,
            now_iso="2026-02-12T13:00:00+00:00",
        )

        self.assertEqual(first.sent_notifications, 1)
        self.assertEqual(second.sent_notifications, 0)
        self.assertEqual(second.skipped_notifications, 1)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("【明日3Q決算】", sender.messages[0])
        self.assertEqual(len(log_repo.rows), 1)
        self.assertEqual(log_repo.rows[0].category, "明日決算")


if __name__ == "__main__":
    unittest.main()

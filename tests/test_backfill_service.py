from __future__ import annotations

import unittest

from kabu_per_bot.backfill_service import refresh_latest_medians_and_signal, resolve_incremental_from_date
from kabu_per_bot.metrics import DailyMetric
from kabu_per_bot.signal import SignalState
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


class _DailyRepo:
    def __init__(self, rows: list[DailyMetric]) -> None:
        self.rows = list(rows)

    def upsert(self, metric: DailyMetric) -> None:
        self.rows = [row for row in self.rows if row.trade_date != metric.trade_date]
        self.rows.append(metric)
        self.rows.sort(key=lambda row: row.trade_date, reverse=True)

    def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
        filtered = [row for row in self.rows if row.ticker == ticker]
        filtered.sort(key=lambda row: row.trade_date, reverse=True)
        return filtered[:limit]


class _MediansRepo:
    def __init__(self) -> None:
        self.rows = []

    def upsert(self, medians) -> None:
        self.rows.append(medians)


class _SignalRepo:
    def __init__(self, latest: SignalState | None = None) -> None:
        self.latest = latest
        self.rows = []

    def get_latest(self, ticker: str) -> SignalState | None:
        _ = ticker
        return self.latest

    def upsert(self, state: SignalState) -> None:
        self.latest = state
        self.rows.append(state)


class BackfillServiceTest(unittest.TestCase):
    def test_resolve_incremental_from_date_without_history(self) -> None:
        from_date = resolve_incremental_from_date(
            latest_trade_date=None,
            to_date="2026-02-12",
            initial_lookback_days=400,
            overlap_days=7,
        )
        self.assertEqual(from_date, "2025-01-08")

    def test_resolve_incremental_from_date_with_history(self) -> None:
        from_date = resolve_incremental_from_date(
            latest_trade_date="2026-02-10",
            to_date="2026-02-12",
            initial_lookback_days=400,
            overlap_days=7,
        )
        self.assertEqual(from_date, "2026-02-03")

    def test_refresh_latest_medians_and_signal(self) -> None:
        ticker = "3901:TSE"
        item = WatchlistItem(
            ticker=ticker,
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
        daily_repo = _DailyRepo(
            rows=[
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-02-05",
                    close_price=100,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=10,
                    psr_value=1,
                    data_source="test",
                    fetched_at="2026-02-05T00:00:00+00:00",
                ),
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-02-04",
                    close_price=110,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=11,
                    psr_value=1.1,
                    data_source="test",
                    fetched_at="2026-02-04T00:00:00+00:00",
                ),
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-02-03",
                    close_price=120,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=12,
                    psr_value=1.2,
                    data_source="test",
                    fetched_at="2026-02-03T00:00:00+00:00",
                ),
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-02-02",
                    close_price=130,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=13,
                    psr_value=1.3,
                    data_source="test",
                    fetched_at="2026-02-02T00:00:00+00:00",
                ),
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-01-30",
                    close_price=140,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=14,
                    psr_value=1.4,
                    data_source="test",
                    fetched_at="2026-01-30T00:00:00+00:00",
                ),
            ]
        )
        medians_repo = _MediansRepo()
        signal_repo = _SignalRepo()

        updated = refresh_latest_medians_and_signal(
            item=item,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            window_1w_days=2,
            window_3m_days=3,
            window_1y_days=5,
        )

        self.assertTrue(updated)
        self.assertEqual(len(medians_repo.rows), 1)
        self.assertEqual(len(signal_repo.rows), 1)
        self.assertEqual(medians_repo.rows[0].median_1w, 10.5)
        self.assertEqual(medians_repo.rows[0].median_3m, 11.0)
        self.assertEqual(medians_repo.rows[0].median_1y, 12.0)
        self.assertEqual(signal_repo.rows[0].category, "超PER割安")

    def test_refresh_latest_medians_and_signal_returns_false_when_no_rows(self) -> None:
        item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
        daily_repo = _DailyRepo(rows=[])
        medians_repo = _MediansRepo()
        signal_repo = _SignalRepo()

        updated = refresh_latest_medians_and_signal(
            item=item,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            window_1w_days=2,
            window_3m_days=3,
            window_1y_days=5,
        )

        self.assertFalse(updated)
        self.assertEqual(len(medians_repo.rows), 0)
        self.assertEqual(len(signal_repo.rows), 0)

    def test_refresh_latest_medians_and_signal_preserves_streak_on_same_trade_date(self) -> None:
        ticker = "3901:TSE"
        item = WatchlistItem(
            ticker=ticker,
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
        daily_repo = _DailyRepo(
            rows=[
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-02-05",
                    close_price=100,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=10,
                    psr_value=1,
                    data_source="test",
                    fetched_at="2026-02-05T00:00:00+00:00",
                ),
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-02-04",
                    close_price=110,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=11,
                    psr_value=1.1,
                    data_source="test",
                    fetched_at="2026-02-04T00:00:00+00:00",
                ),
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-02-03",
                    close_price=120,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=12,
                    psr_value=1.2,
                    data_source="test",
                    fetched_at="2026-02-03T00:00:00+00:00",
                ),
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-02-02",
                    close_price=130,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=13,
                    psr_value=1.3,
                    data_source="test",
                    fetched_at="2026-02-02T00:00:00+00:00",
                ),
                DailyMetric(
                    ticker=ticker,
                    trade_date="2026-01-30",
                    close_price=140,
                    eps_forecast=10,
                    sales_forecast=100,
                    per_value=14,
                    psr_value=1.4,
                    data_source="test",
                    fetched_at="2026-01-30T00:00:00+00:00",
                ),
            ]
        )
        signal_repo = _SignalRepo(
            latest=SignalState(
                ticker=ticker,
                trade_date="2026-02-05",
                metric_type=MetricType.PER,
                metric_value=10.0,
                under_1w=True,
                under_3m=True,
                under_1y=True,
                combo="1Y+3M+1W",
                is_strong=True,
                category="超PER割安",
                streak_days=7,
                updated_at="2026-02-05T01:00:00+00:00",
            )
        )
        medians_repo = _MediansRepo()

        updated = refresh_latest_medians_and_signal(
            item=item,
            daily_metrics_repo=daily_repo,
            medians_repo=medians_repo,
            signal_state_repo=signal_repo,
            window_1w_days=2,
            window_3m_days=3,
            window_1y_days=5,
        )

        self.assertTrue(updated)
        self.assertEqual(signal_repo.rows[-1].trade_date, "2026-02-05")
        self.assertEqual(signal_repo.rows[-1].streak_days, 7)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from kabu_per_bot.market_data import MarketDataSnapshot
from kabu_per_bot.metrics import DailyMetric, build_daily_metric, calculate_metric_medians
from kabu_per_bot.watchlist import MetricType


class MetricsTest(unittest.TestCase):
    def test_build_daily_metric_per_formula(self) -> None:
        snapshot = MarketDataSnapshot.create(
            ticker="3901:TSE",
            close_price=1200.0,
            eps_forecast=100.0,
            sales_forecast=4000.0,
            source="株探",
            earnings_date="2026-05-10",
        )
        metric = build_daily_metric(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            snapshot=snapshot,
        )
        self.assertEqual(metric.per_value, 12.0)
        self.assertAlmostEqual(metric.psr_value or 0.0, 0.3)

    def test_build_daily_metric_per_is_none_when_eps_invalid(self) -> None:
        snapshot = MarketDataSnapshot.create(
            ticker="3901:TSE",
            close_price=1200.0,
            eps_forecast=0.0,
            sales_forecast=4000.0,
            source="株探",
            earnings_date="2026-05-10",
        )
        metric = build_daily_metric(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            snapshot=snapshot,
        )
        self.assertIsNone(metric.per_value)
        self.assertEqual(metric.missing_fields(metric_type=MetricType.PER), ["eps_forecast"])

    def test_calculate_metric_medians(self) -> None:
        metrics = [
            DailyMetric(
                ticker="3901:TSE",
                trade_date="2026-02-12",
                close_price=100.0,
                eps_forecast=10.0,
                sales_forecast=100.0,
                per_value=10.0,
                psr_value=1.0,
                data_source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            ),
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
        ]
        medians = calculate_metric_medians(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            latest_first_metrics=metrics,
            window_1w_days=2,
            window_3m_days=2,
            window_1y_days=2,
        )
        self.assertEqual(medians.median_1w, 12.5)
        self.assertEqual(medians.median_3m, 12.5)
        self.assertEqual(medians.median_1y, 12.5)

    def test_calculate_metric_medians_returns_none_when_not_enough_data(self) -> None:
        metrics = [
            DailyMetric(
                ticker="3901:TSE",
                trade_date="2026-02-12",
                close_price=100.0,
                eps_forecast=10.0,
                sales_forecast=100.0,
                per_value=10.0,
                psr_value=1.0,
                data_source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            )
        ]
        medians = calculate_metric_medians(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            latest_first_metrics=metrics,
            window_1w_days=2,
            window_3m_days=3,
            window_1y_days=4,
        )
        self.assertIsNone(medians.median_1w)
        self.assertEqual(medians.insufficient_windows(), ["1W", "3M", "1Y"])


if __name__ == "__main__":
    unittest.main()

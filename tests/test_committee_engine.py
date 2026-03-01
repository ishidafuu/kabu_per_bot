from __future__ import annotations

import unittest

from kabu_per_bot.committee import CommitteeContext, CommitteeEvaluationEngine
from kabu_per_bot.market_data import MarketDataSnapshot
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.watchlist import MetricType


def _metric(*, trade_date: str, close_price: float, per: float | None = None, psr: float | None = None) -> DailyMetric:
    return DailyMetric(
        ticker="3901:TSE",
        trade_date=trade_date,
        close_price=close_price,
        eps_forecast=10.0,
        sales_forecast=100.0,
        per_value=per,
        psr_value=psr,
        data_source="株探",
        fetched_at="2026-03-01T09:00:00+00:00",
    )


class CommitteeEvaluationEngineTest(unittest.TestCase):
    def test_evaluate_outputs_6_lenses_and_2_axes(self) -> None:
        recent = tuple(
            _metric(trade_date=f"2026-02-{day:02d}", close_price=200.0 - day, per=14.0 - (day * 0.05))
            for day in range(1, 70)
        )
        context = CommitteeContext(
            ticker="3901:TSE",
            company_name="富士フイルム",
            trade_date="2026-03-01",
            metric_type=MetricType.PER,
            latest_metric=recent[0],
            recent_metrics=recent,
            latest_medians=MetricMedians(
                ticker="3901:TSE",
                trade_date="2026-03-01",
                median_1w=14.2,
                median_3m=14.5,
                median_1y=15.0,
                source_metric_type=MetricType.PER,
                calculated_at="2026-03-01T09:00:00+00:00",
            ),
            market_snapshot=MarketDataSnapshot.create(
                ticker="3901:TSE",
                close_price=recent[0].close_price,
                eps_forecast=10.0,
                sales_forecast=100.0,
                earnings_date="2026-03-20",
                source="株探",
                fetched_at="2026-03-01T09:00:00+00:00",
            ),
            baseline_summary={
                "business_summary": "印刷とヘルスケアを柱に事業展開",
                "growth_driver": "医療関連の伸長",
                "debt_comment": "有利子負債は許容範囲",
                "cf_comment": "営業CFは安定推移",
            },
            baseline_reliability_score=4,
            baseline_updated_at="2026-03-01T18:00:00+09:00",
        )

        engine = CommitteeEvaluationEngine()
        result = engine.evaluate(context)

        self.assertEqual(len(result.lenses), 6)
        self.assertGreaterEqual(result.confidence, 1)
        self.assertLessEqual(result.confidence, 5)
        self.assertGreaterEqual(result.strength, 1)
        self.assertLessEqual(result.strength, 5)
        for lens in result.lenses:
            self.assertLessEqual(len(lens.lines), 3)
            self.assertGreaterEqual(lens.confidence, 1)
            self.assertLessEqual(lens.confidence, 5)
            self.assertGreaterEqual(lens.strength, 1)
            self.assertLessEqual(lens.strength, 5)

    def test_evaluate_handles_missing_baseline(self) -> None:
        recent = (
            _metric(trade_date="2026-03-01", close_price=120.0, per=20.0),
            _metric(trade_date="2026-02-28", close_price=122.0, per=20.1),
            _metric(trade_date="2026-02-27", close_price=121.0, per=20.2),
            _metric(trade_date="2026-02-26", close_price=118.0, per=19.9),
            _metric(trade_date="2026-02-25", close_price=119.0, per=20.3),
            _metric(trade_date="2026-02-24", close_price=117.0, per=19.7),
        )
        context = CommitteeContext(
            ticker="3901:TSE",
            company_name="富士フイルム",
            trade_date="2026-03-01",
            metric_type=MetricType.PER,
            latest_metric=recent[0],
            recent_metrics=recent,
            latest_medians=None,
            market_snapshot=None,
        )

        engine = CommitteeEvaluationEngine()
        result = engine.evaluate(context)

        self.assertGreaterEqual(len(result.missing_fields), 1)
        business = next(item for item in result.lenses if item.key.value == "business")
        self.assertLessEqual(len(business.lines), 3)
        self.assertGreaterEqual(business.strength, 1)


if __name__ == "__main__":
    unittest.main()

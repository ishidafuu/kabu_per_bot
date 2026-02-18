from __future__ import annotations

import unittest

from kabu_per_bot.backfill import build_daily_metrics_from_jquants_v2
from kabu_per_bot.watchlist import MetricType


class BackfillTest(unittest.TestCase):
    def test_build_daily_metrics_applies_latest_forecast_by_disclosed_date(self) -> None:
        bars = [
            {"Date": "2026-02-17", "Code": "3984", "C": "100"},
            {"Date": "2026-02-18", "Code": "3984", "C": "110"},
            {"Date": "2026-02-19", "Code": "3984", "C": "120"},
        ]
        fin_summary = [
            {
                "DiscDate": "2026-02-18",
                "DiscTime": "08:00:00",
                "Code": "3984",
                "FEPS": "11",
                "FSales": "220",
            },
            {
                "DiscDate": "2026-02-19",
                "DiscTime": "15:30:00",
                "Code": "3984",
                "FEPS": "12",
                "FSales": "",
            },
        ]

        rows = build_daily_metrics_from_jquants_v2(
            ticker="3984:TSE",
            metric_type=MetricType.PER,
            bars_daily_rows=bars,
            fin_summary_rows=fin_summary,
            fetched_at="2026-02-20T00:00:00+00:00",
        )

        self.assertEqual([row.trade_date for row in rows], ["2026-02-17", "2026-02-18", "2026-02-19"])

        self.assertIsNone(rows[0].eps_forecast)
        self.assertIsNone(rows[0].sales_forecast)
        self.assertIsNone(rows[0].per_value)
        self.assertIsNone(rows[0].psr_value)

        self.assertEqual(rows[1].eps_forecast, 11.0)
        self.assertEqual(rows[1].sales_forecast, 220.0)
        self.assertAlmostEqual(rows[1].per_value or 0.0, 10.0)
        self.assertAlmostEqual(rows[1].psr_value or 0.0, 0.5)

        # 2/19はEPSのみ更新、売上予想は直前値を維持する
        self.assertEqual(rows[2].eps_forecast, 12.0)
        self.assertEqual(rows[2].sales_forecast, 220.0)
        self.assertAlmostEqual(rows[2].per_value or 0.0, 10.0)
        self.assertAlmostEqual(rows[2].psr_value or 0.0, 120.0 / 220.0)


if __name__ == "__main__":
    unittest.main()


from __future__ import annotations

import unittest

from kabu_per_bot.technical import (
    PriceBarDaily,
    TechnicalAlertOperator,
    TechnicalAlertRule,
    TechnicalAlertState,
    TechnicalIndicatorsDaily,
    TechnicalSyncState,
)


class TechnicalModelTest(unittest.TestCase):
    def test_price_bar_round_trip(self) -> None:
        row = PriceBarDaily(
            ticker="3901:tse",
            trade_date="2026-03-07",
            code="3901",
            date="20260307",
            open_price=100.0,
            high_price=105.0,
            low_price=99.0,
            close_price=104.0,
            volume=123456,
            turnover_value=12500000.0,
            adj_open=100.0,
            adj_high=105.0,
            adj_low=99.0,
            adj_close=104.0,
            adj_volume=123456.0,
            source="J-Quants LITE",
            fetched_at="2026-03-08T00:00:00+00:00",
            data_source_plan="light",
            raw_payload_version="v2",
            updated_at="2026-03-08T00:10:00+00:00",
        )

        restored = PriceBarDaily.from_document(row.to_document())
        self.assertEqual(restored.ticker, "3901:TSE")
        self.assertEqual(restored.trade_date, "2026-03-07")
        self.assertEqual(restored.date, "2026-03-07")
        self.assertEqual(restored.close_price, 104.0)

    def test_technical_indicators_round_trip(self) -> None:
        row = TechnicalIndicatorsDaily(
            ticker="3901:tse",
            trade_date="2026-03-07",
            schema_version=1,
            calculated_at="2026-03-08T00:00:00+00:00",
            values={
                "close_vs_ma25": 3.5,
                "above_ma5": True,
                "days_from_52w_high": 12,
                "candle_type": "bull",
            },
        )

        restored = TechnicalIndicatorsDaily.from_document(row.to_document())
        self.assertEqual(restored.get_value("close_vs_ma25"), 3.5)
        self.assertTrue(restored.get_value("above_ma5"))
        self.assertEqual(restored.get_value("days_from_52w_high"), 12)
        self.assertEqual(restored.get_value("candle_type"), "bull")

    def test_technical_sync_state_round_trip(self) -> None:
        row = TechnicalSyncState(
            ticker="3901:tse",
            latest_fetched_trade_date="2026-03-07",
            latest_calculated_trade_date="2026-03-06",
            last_run_at="2026-03-08T00:00:00+00:00",
            last_status="SUCCESS",
            last_fetch_from="2026-02-05",
            last_fetch_to="2026-03-07",
            last_error=None,
            last_full_refresh_at="2026-03-01T00:00:00+00:00",
            schema_version=1,
        )

        restored = TechnicalSyncState.from_document(row.to_document())
        self.assertEqual(restored.ticker, "3901:TSE")
        self.assertEqual(restored.latest_fetched_trade_date, "2026-03-07")
        self.assertEqual(restored.schema_version, 1)

    def test_alert_rule_round_trip(self) -> None:
        rule = TechnicalAlertRule.create(
            ticker="3901:tse",
            rule_name="25日線上抜け",
            field_key="close_vs_ma25",
            operator=TechnicalAlertOperator.GTE,
            threshold_value=0.0,
            note="終値基準",
            created_at="2026-03-08T00:00:00+00:00",
            updated_at="2026-03-08T00:00:00+00:00",
            rule_id="rule-ma25-up",
        )

        restored = TechnicalAlertRule.from_document(rule.to_document())
        self.assertEqual(restored.rule_id, "rule-ma25-up")
        self.assertEqual(restored.ticker, "3901:TSE")
        self.assertEqual(restored.operator, TechnicalAlertOperator.GTE)
        self.assertEqual(restored.threshold_value, 0.0)

    def test_alert_rule_rejects_invalid_threshold_shape(self) -> None:
        with self.assertRaises(ValueError):
            TechnicalAlertRule.create(
                ticker="3901:TSE",
                rule_name="invalid",
                field_key="above_ma5",
                operator=TechnicalAlertOperator.IS_TRUE,
                threshold_value=1.0,
            )

    def test_alert_state_round_trip(self) -> None:
        state = TechnicalAlertState(
            ticker="3901:tse",
            rule_id="rule-ma25-up",
            last_evaluated_trade_date="2026-03-07",
            last_condition_met=True,
            last_triggered_at="2026-03-08T00:00:00+00:00",
            updated_at="2026-03-08T00:10:00+00:00",
        )

        restored = TechnicalAlertState.from_document(state.to_document())
        self.assertEqual(restored.ticker, "3901:TSE")
        self.assertEqual(restored.rule_id, "rule-ma25-up")
        self.assertTrue(restored.last_condition_met)


if __name__ == "__main__":
    unittest.main()

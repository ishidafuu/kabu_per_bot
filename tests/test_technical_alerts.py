from __future__ import annotations

import unittest

from kabu_per_bot.technical import (
    TechnicalAlertOperator,
    TechnicalAlertRule,
    TechnicalAlertState,
    TechnicalIndicatorsDaily,
)
from kabu_per_bot.technical_alerts import (
    build_technical_alert_state,
    describe_technical_alert_threshold,
    evaluate_technical_alert_rule,
)


def _indicator(trade_date: str, **values) -> TechnicalIndicatorsDaily:
    return TechnicalIndicatorsDaily(
        ticker="3901:TSE",
        trade_date=trade_date,
        schema_version=1,
        calculated_at=f"{trade_date}T06:00:00+00:00",
        values=values,
    )


class TechnicalAlertEvaluationTest(unittest.TestCase):
    def test_event_rule_triggers_when_current_day_is_true(self) -> None:
        rule = TechnicalAlertRule.create(
            ticker="3901:TSE",
            rule_name="25日線上抜け",
            field_key="cross_up_ma25",
            operator=TechnicalAlertOperator.IS_TRUE,
            rule_id="rule-1",
        )

        evaluation = evaluate_technical_alert_rule(
            rule=rule,
            current=_indicator("2026-03-08", cross_up_ma25=True),
            previous=None,
            previous_state=None,
        )

        self.assertTrue(evaluation.condition_met)
        self.assertTrue(evaluation.should_trigger)
        self.assertIsNone(evaluation.previous_condition_met)

    def test_numeric_rule_triggers_only_on_cross(self) -> None:
        rule = TechnicalAlertRule.create(
            ticker="3901:TSE",
            rule_name="25日線回復",
            field_key="close_vs_ma25",
            operator=TechnicalAlertOperator.GTE,
            threshold_value=0.0,
            rule_id="rule-2",
        )

        evaluation = evaluate_technical_alert_rule(
            rule=rule,
            current=_indicator("2026-03-08", close_vs_ma25=1.2),
            previous=_indicator("2026-03-07", close_vs_ma25=-0.5),
            previous_state=None,
        )

        self.assertTrue(evaluation.condition_met)
        self.assertFalse(evaluation.previous_condition_met)
        self.assertTrue(evaluation.should_trigger)

    def test_numeric_rule_does_not_trigger_without_previous_context(self) -> None:
        rule = TechnicalAlertRule.create(
            ticker="3901:TSE",
            rule_name="出来高急増",
            field_key="volume_ratio",
            operator=TechnicalAlertOperator.GTE,
            threshold_value=2.0,
            rule_id="rule-3",
        )

        evaluation = evaluate_technical_alert_rule(
            rule=rule,
            current=_indicator("2026-03-08", volume_ratio=2.5),
            previous=None,
            previous_state=None,
        )

        self.assertTrue(evaluation.condition_met)
        self.assertFalse(evaluation.should_trigger)

    def test_same_day_rerun_uses_alert_state_to_stop_duplicate_trigger(self) -> None:
        rule = TechnicalAlertRule.create(
            ticker="3901:TSE",
            rule_name="25日線回復",
            field_key="close_vs_ma25",
            operator=TechnicalAlertOperator.GTE,
            threshold_value=0.0,
            rule_id="rule-4",
        )
        previous_state = TechnicalAlertState(
            ticker="3901:TSE",
            rule_id="rule-4",
            last_evaluated_trade_date="2026-03-08",
            last_condition_met=True,
            last_triggered_at="2026-03-08T06:30:00+00:00",
            updated_at="2026-03-08T06:30:00+00:00",
        )

        evaluation = evaluate_technical_alert_rule(
            rule=rule,
            current=_indicator("2026-03-08", close_vs_ma25=0.8),
            previous=_indicator("2026-03-07", close_vs_ma25=-0.2),
            previous_state=previous_state,
        )

        self.assertTrue(evaluation.condition_met)
        self.assertTrue(evaluation.previous_condition_met)
        self.assertFalse(evaluation.should_trigger)

    def test_invalid_field_operator_combination_is_reported(self) -> None:
        rule = TechnicalAlertRule.create(
            ticker="3901:TSE",
            rule_name="不正組み合わせ",
            field_key="candle_type",
            operator=TechnicalAlertOperator.GTE,
            threshold_value=1.0,
            rule_id="rule-5",
        )

        evaluation = evaluate_technical_alert_rule(
            rule=rule,
            current=_indicator("2026-03-08", candle_type="bull"),
            previous=None,
            previous_state=None,
        )

        self.assertFalse(evaluation.is_supported)
        self.assertEqual(evaluation.invalid_reason, "numeric operator requires numeric field_key")

    def test_build_technical_alert_state_preserves_last_triggered_at(self) -> None:
        rule = TechnicalAlertRule.create(
            ticker="3901:TSE",
            rule_name="25日線上抜け",
            field_key="cross_up_ma25",
            operator=TechnicalAlertOperator.IS_TRUE,
            rule_id="rule-6",
        )
        evaluation = evaluate_technical_alert_rule(
            rule=rule,
            current=_indicator("2026-03-08", cross_up_ma25=False),
            previous=None,
            previous_state=None,
        )
        state = build_technical_alert_state(
            evaluation=evaluation,
            previous_state=TechnicalAlertState(
                ticker="3901:TSE",
                rule_id="rule-6",
                last_evaluated_trade_date="2026-03-07",
                last_condition_met=True,
                last_triggered_at="2026-03-07T06:30:00+00:00",
                updated_at="2026-03-07T06:30:00+00:00",
            ),
            updated_at="2026-03-08T06:30:00+00:00",
        )
        self.assertEqual(state.last_triggered_at, "2026-03-07T06:30:00+00:00")
        self.assertFalse(state.last_condition_met)

    def test_describe_technical_alert_threshold(self) -> None:
        rule = TechnicalAlertRule.create(
            ticker="3901:TSE",
            rule_name="レンジ外れ",
            field_key="close_vs_ma25",
            operator=TechnicalAlertOperator.OUTSIDE,
            threshold_value=-5.0,
            threshold_upper=5.0,
            rule_id="rule-7",
        )
        self.assertEqual(describe_technical_alert_threshold(rule), "< -5.00 または > 5.00")


if __name__ == "__main__":
    unittest.main()

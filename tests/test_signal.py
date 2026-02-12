from __future__ import annotations

import unittest

from kabu_per_bot.metrics import MetricMedians
from kabu_per_bot.signal import (
    NotificationLogEntry,
    SignalState,
    build_signal_state,
    evaluate_cooldown,
    evaluate_signal,
)
from kabu_per_bot.watchlist import MetricType


class SignalTest(unittest.TestCase):
    def test_evaluate_signal_strong_priority(self) -> None:
        medians = MetricMedians(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            median_1w=12.0,
            median_3m=13.0,
            median_1y=14.0,
            source_metric_type=MetricType.PER,
            calculated_at="2026-02-12T00:00:00+00:00",
        )
        signal = evaluate_signal(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            metric_value=10.0,
            medians=medians,
        )
        self.assertTrue(signal.is_strong)
        self.assertEqual(signal.category, "超PER割安")
        self.assertEqual(signal.combo, "1Y+3M+1W")

    def test_build_signal_state_streak_increment(self) -> None:
        medians = MetricMedians(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            median_1w=11.0,
            median_3m=12.0,
            median_1y=13.0,
            source_metric_type=MetricType.PER,
            calculated_at="2026-02-12T00:00:00+00:00",
        )
        current = evaluate_signal(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            metric_value=10.0,
            medians=medians,
        )
        previous = SignalState(
            ticker="3901:TSE",
            trade_date="2026-02-11",
            metric_type=MetricType.PER,
            metric_value=9.8,
            under_1w=True,
            under_3m=True,
            under_1y=True,
            combo="1Y+3M+1W",
            is_strong=True,
            category="超PER割安",
            streak_days=4,
            updated_at="2026-02-11T00:00:00+00:00",
        )
        state = build_signal_state(evaluation=current, previous_state=previous)
        self.assertEqual(state.streak_days, 5)

    def test_build_signal_state_resets_when_condition_changes(self) -> None:
        medians = MetricMedians(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            median_1w=9.0,
            median_3m=12.0,
            median_1y=13.0,
            source_metric_type=MetricType.PER,
            calculated_at="2026-02-12T00:00:00+00:00",
        )
        current = evaluate_signal(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            metric_value=10.0,
            medians=medians,
        )
        previous = SignalState(
            ticker="3901:TSE",
            trade_date="2026-02-11",
            metric_type=MetricType.PER,
            metric_value=9.8,
            under_1w=True,
            under_3m=True,
            under_1y=True,
            combo="1Y+3M+1W",
            is_strong=True,
            category="超PER割安",
            streak_days=4,
            updated_at="2026-02-11T00:00:00+00:00",
        )
        state = build_signal_state(evaluation=current, previous_state=previous)
        self.assertEqual(state.combo, "1Y+3M")
        self.assertEqual(state.streak_days, 1)

    def test_evaluate_cooldown_blocks_same_condition_within_2h(self) -> None:
        decision = evaluate_cooldown(
            now_iso="2026-02-12T10:00:00+00:00",
            cooldown_hours=2,
            candidate_ticker="3901:TSE",
            candidate_category="PER割安",
            candidate_condition_key="PER:1Y+3M",
            candidate_is_strong=False,
            recent_entries=[
                NotificationLogEntry(
                    entry_id="1",
                    ticker="3901:TSE",
                    category="PER割安",
                    condition_key="PER:1Y+3M",
                    sent_at="2026-02-12T08:30:00+00:00",
                    channel="DISCORD",
                    payload_hash="a",
                    is_strong=False,
                )
            ],
        )
        self.assertFalse(decision.should_send)

    def test_evaluate_cooldown_allows_normal_to_strong_transition(self) -> None:
        decision = evaluate_cooldown(
            now_iso="2026-02-12T10:00:00+00:00",
            cooldown_hours=2,
            candidate_ticker="3901:TSE",
            candidate_category="超PER割安",
            candidate_condition_key="PER:1Y+3M+1W",
            candidate_is_strong=True,
            recent_entries=[
                NotificationLogEntry(
                    entry_id="1",
                    ticker="3901:TSE",
                    category="PER割安",
                    condition_key="PER:1Y+3M",
                    sent_at="2026-02-12T09:00:00+00:00",
                    channel="DISCORD",
                    payload_hash="a",
                    is_strong=False,
                )
            ],
        )
        self.assertTrue(decision.should_send)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from kabu_per_bot.immediate_schedule import ImmediateSchedule, evaluate_window_schedule, validate_immediate_schedule


class ImmediateScheduleTest(unittest.TestCase):
    def test_validate_rejects_overlap(self) -> None:
        schedule = ImmediateSchedule(
            enabled=True,
            timezone="Asia/Tokyo",
            open_window_start="09:00",
            open_window_end="10:00",
            open_window_interval_min=15,
            close_window_start="09:30",
            close_window_end="10:30",
            close_window_interval_min=10,
        )
        with self.assertRaises(ValueError):
            validate_immediate_schedule(schedule)

    def test_evaluate_window_schedule_matches_interval(self) -> None:
        schedule = ImmediateSchedule.default()
        decision = evaluate_window_schedule(
            schedule=schedule,
            window_kind="open",
            now_iso="2026-02-19T09:30:00+09:00",
        )
        self.assertTrue(decision.should_run)

    def test_evaluate_window_schedule_skips_when_interval_not_due(self) -> None:
        schedule = ImmediateSchedule.default()
        decision = evaluate_window_schedule(
            schedule=schedule,
            window_kind="open",
            now_iso="2026-02-19T09:31:00+09:00",
        )
        self.assertFalse(decision.should_run)

    def test_evaluate_window_schedule_rejects_unknown_window_kind(self) -> None:
        schedule = ImmediateSchedule.default()
        with self.assertRaises(ValueError):
            evaluate_window_schedule(
                schedule=schedule,
                window_kind="intraday",  # type: ignore[arg-type]
                now_iso="2026-02-19T09:30:00+09:00",
            )


if __name__ == "__main__":
    unittest.main()

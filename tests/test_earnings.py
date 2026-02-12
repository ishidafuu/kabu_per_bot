from __future__ import annotations

import unittest

from kabu_per_bot.earnings import EarningsCalendarEntry, select_next_week_entries, select_tomorrow_entries


class EarningsTest(unittest.TestCase):
    def test_select_next_week_entries(self) -> None:
        entries = [
            EarningsCalendarEntry(
                ticker="3901:TSE",
                earnings_date="2026-02-16",
                earnings_time="15:00",
                quarter="3Q",
                source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            ),
            EarningsCalendarEntry(
                ticker="3902:TSE",
                earnings_date="2026-02-25",
                earnings_time=None,
                quarter=None,
                source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            ),
        ]
        # 2026-02-14(土) の来週は 2026-02-16(月)〜2026-02-22(日)
        selected = select_next_week_entries(entries, today="2026-02-14")
        self.assertEqual([entry.ticker for entry in selected], ["3901:TSE"])

    def test_select_tomorrow_entries(self) -> None:
        entries = [
            EarningsCalendarEntry(
                ticker="3901:TSE",
                earnings_date="2026-02-13",
                earnings_time="15:00",
                quarter="3Q",
                source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            ),
            EarningsCalendarEntry(
                ticker="3902:TSE",
                earnings_date="2026-02-14",
                earnings_time=None,
                quarter=None,
                source="株探",
                fetched_at="2026-02-12T00:00:00+00:00",
            ),
        ]
        selected = select_tomorrow_entries(entries, today="2026-02-12")
        self.assertEqual([entry.ticker for entry in selected], ["3901:TSE"])


if __name__ == "__main__":
    unittest.main()

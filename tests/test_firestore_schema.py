from __future__ import annotations

import unittest

from kabu_per_bot.storage.firestore_schema import (
    ALL_COLLECTIONS,
    COLLECTION_DAILY_METRICS,
    COLLECTION_EARNINGS_CALENDAR,
    COLLECTION_METRIC_MEDIANS,
    COLLECTION_NOTIFICATION_LOG,
    COLLECTION_SIGNAL_STATE,
    COLLECTION_WATCHLIST,
    COLLECTION_WATCHLIST_HISTORY,
    daily_metrics_doc_id,
    earnings_calendar_doc_id,
    normalize_ticker,
    notification_condition_key,
    signal_state_doc_id,
    watchlist_doc_id,
)


class FirestoreSchemaTest(unittest.TestCase):
    def test_collections_match_mvp_set(self) -> None:
        self.assertEqual(
            set(ALL_COLLECTIONS),
            {
                COLLECTION_WATCHLIST,
                COLLECTION_WATCHLIST_HISTORY,
                COLLECTION_DAILY_METRICS,
                COLLECTION_METRIC_MEDIANS,
                COLLECTION_SIGNAL_STATE,
                COLLECTION_EARNINGS_CALENDAR,
                COLLECTION_NOTIFICATION_LOG,
            },
        )

    def test_ticker_normalization(self) -> None:
        self.assertEqual(normalize_ticker("3901:tse"), "3901:TSE")
        with self.assertRaises(ValueError):
            normalize_ticker("abc")

    def test_unique_doc_ids(self) -> None:
        self.assertEqual(watchlist_doc_id("3901:tse"), "3901:TSE")
        self.assertEqual(
            daily_metrics_doc_id("3901:tse", "2026-02-12"),
            "3901:TSE|2026-02-12",
        )
        self.assertEqual(
            signal_state_doc_id("3901:tse", "2026-02-12"),
            "3901:TSE|2026-02-12",
        )
        self.assertEqual(
            earnings_calendar_doc_id("3901:tse", "2026-05-10", "1Q"),
            "3901:TSE|2026-05-10|1Q",
        )

    def test_notification_condition_key_is_stable(self) -> None:
        key1 = notification_condition_key(
            ticker="3901:tse",
            category="PER割安",
            condition="1Y+3M",
        )
        key2 = notification_condition_key(
            ticker="3901:TSE",
            category="PER割安",
            condition="1Y+3M",
        )
        self.assertEqual(key1, key2)


if __name__ == "__main__":
    unittest.main()


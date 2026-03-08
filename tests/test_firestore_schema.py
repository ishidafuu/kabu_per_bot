from __future__ import annotations

import unittest

from kabu_per_bot.storage.firestore_schema import (
    ALL_COLLECTIONS,
    COLLECTION_BASELINE_RESEARCH,
    COLLECTION_DAILY_METRICS,
    COLLECTION_EARNINGS_CALENDAR,
    COLLECTION_GLOBAL_SETTINGS,
    COLLECTION_INTEL_SEEN,
    COLLECTION_JOB_RUN,
    COLLECTION_METRIC_MEDIANS,
    COLLECTION_NOTIFICATION_LOG,
    COLLECTION_PRICE_BARS_DAILY,
    COLLECTION_SIGNAL_STATE,
    COLLECTION_TECHNICAL_ALERT_RULES,
    COLLECTION_TECHNICAL_ALERT_STATE,
    COLLECTION_TECHNICAL_INDICATORS_DAILY,
    COLLECTION_TECHNICAL_PROFILES,
    COLLECTION_TECHNICAL_SYNC_STATE,
    COLLECTION_WATCHLIST,
    COLLECTION_WATCHLIST_HISTORY,
    INITIAL_COLLECTIONS,
    daily_metrics_doc_id,
    earnings_calendar_doc_id,
    normalize_ticker,
    notification_condition_key,
    price_bars_daily_doc_id,
    signal_state_doc_id,
    technical_alert_rule_doc_id,
    technical_alert_state_doc_id,
    technical_indicators_daily_doc_id,
    technical_profile_doc_id,
    technical_sync_state_doc_id,
    watchlist_doc_id,
)


class FirestoreSchemaTest(unittest.TestCase):
    def test_initial_collections_match_mvp_set(self) -> None:
        self.assertEqual(
            set(INITIAL_COLLECTIONS),
            {
                COLLECTION_WATCHLIST,
                COLLECTION_WATCHLIST_HISTORY,
                COLLECTION_DAILY_METRICS,
                COLLECTION_METRIC_MEDIANS,
                COLLECTION_SIGNAL_STATE,
                COLLECTION_EARNINGS_CALENDAR,
                COLLECTION_NOTIFICATION_LOG,
                COLLECTION_JOB_RUN,
                COLLECTION_INTEL_SEEN,
                COLLECTION_GLOBAL_SETTINGS,
                COLLECTION_BASELINE_RESEARCH,
            },
        )

    def test_all_collections_include_technical_set(self) -> None:
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
                COLLECTION_JOB_RUN,
                COLLECTION_INTEL_SEEN,
                COLLECTION_GLOBAL_SETTINGS,
                COLLECTION_BASELINE_RESEARCH,
                COLLECTION_PRICE_BARS_DAILY,
                COLLECTION_TECHNICAL_INDICATORS_DAILY,
                COLLECTION_TECHNICAL_SYNC_STATE,
                COLLECTION_TECHNICAL_ALERT_RULES,
                COLLECTION_TECHNICAL_ALERT_STATE,
                COLLECTION_TECHNICAL_PROFILES,
            },
        )

    def test_ticker_normalization(self) -> None:
        self.assertEqual(normalize_ticker("3901:tse"), "3901:TSE")
        with self.assertRaises(ValueError):
            normalize_ticker("abc")
        with self.assertRaises(ValueError):
            normalize_ticker("3901:TYO")

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
            price_bars_daily_doc_id("3901:tse", "2026-02-12"),
            "3901:TSE|2026-02-12",
        )
        self.assertEqual(
            technical_indicators_daily_doc_id("3901:tse", "2026-02-12"),
            "3901:TSE|2026-02-12",
        )
        self.assertEqual(technical_sync_state_doc_id("3901:tse"), "3901:TSE")
        self.assertEqual(
            technical_alert_rule_doc_id("3901:tse", "rule-1"),
            "3901:TSE|rule-1",
        )
        self.assertEqual(
            technical_alert_state_doc_id("3901:tse", "rule-1"),
            "3901:TSE|rule-1",
        )
        self.assertEqual(technical_profile_doc_id("system_small_growth"), "system_small_growth")
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

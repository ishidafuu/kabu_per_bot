from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.earnings import EarningsCalendarEntry
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.signal import NotificationLogEntry, SignalState
from kabu_per_bot.storage.firestore_daily_metrics_repository import FirestoreDailyMetricsRepository
from kabu_per_bot.storage.firestore_earnings_calendar_repository import FirestoreEarningsCalendarRepository
from kabu_per_bot.storage.firestore_metric_medians_repository import FirestoreMetricMediansRepository
from kabu_per_bot.storage.firestore_notification_log_repository import FirestoreNotificationLogRepository
from kabu_per_bot.storage.firestore_signal_state_repository import FirestoreSignalStateRepository
from kabu_per_bot.watchlist import MetricType


@dataclass
class FakeSnapshot:
    exists: bool
    data: dict | None = None

    def to_dict(self) -> dict | None:
        return self.data


@dataclass
class FakeDocumentRef:
    path: str
    db: dict[str, dict] = field(default_factory=dict)

    def set(self, data: dict, merge: bool = False) -> None:
        self.db[self.path] = dict(data)

    def get(self) -> FakeSnapshot:
        if self.path not in self.db:
            return FakeSnapshot(exists=False, data=None)
        return FakeSnapshot(exists=True, data=dict(self.db[self.path]))


@dataclass
class FakeCollectionRef:
    path: str
    db: dict[str, dict] = field(default_factory=dict)

    def document(self, document_id: str) -> FakeDocumentRef:
        return FakeDocumentRef(path=f"{self.path}/{document_id}", db=self.db)

    def stream(self) -> list[FakeSnapshot]:
        prefix = f"{self.path}/"
        return [
            FakeSnapshot(exists=True, data=dict(value))
            for key, value in self.db.items()
            if key.startswith(prefix)
        ]


@dataclass
class FakeFirestoreClient:
    db: dict[str, dict] = field(default_factory=dict)

    def collection(self, name: str) -> FakeCollectionRef:
        return FakeCollectionRef(path=name, db=self.db)


class FirestoreMetricRepositoriesTest(unittest.TestCase):
    def test_daily_metrics_repository(self) -> None:
        repo = FirestoreDailyMetricsRepository(FakeFirestoreClient())
        metric = DailyMetric(
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
        repo.upsert(metric)
        found = repo.get("3901:TSE", "2026-02-12")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.per_value, 10.0)

    def test_metric_medians_repository(self) -> None:
        repo = FirestoreMetricMediansRepository(FakeFirestoreClient())
        row = MetricMedians(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            median_1w=10.0,
            median_3m=11.0,
            median_1y=12.0,
            source_metric_type=MetricType.PER,
            calculated_at="2026-02-12T00:00:00+00:00",
        )
        repo.upsert(row)
        found = repo.get("3901:TSE", "2026-02-12")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.median_1y, 12.0)

    def test_signal_and_notification_repositories(self) -> None:
        client = FakeFirestoreClient()
        state_repo = FirestoreSignalStateRepository(client)
        log_repo = FirestoreNotificationLogRepository(client)
        state_repo.upsert(
            SignalState(
                ticker="3901:TSE",
                trade_date="2026-02-12",
                metric_type=MetricType.PER,
                metric_value=10.0,
                under_1w=True,
                under_3m=True,
                under_1y=True,
                combo="1Y+3M+1W",
                is_strong=True,
                category="超PER割安",
                streak_days=2,
                updated_at="2026-02-12T00:00:00+00:00",
            )
        )
        latest = state_repo.get_latest("3901:TSE")
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.streak_days, 2)

        log_repo.append(
            NotificationLogEntry(
                entry_id="log1",
                ticker="3901:TSE",
                category="超PER割安",
                condition_key="PER:1Y+3M+1W",
                sent_at="2026-02-12T00:00:00+00:00",
                channel="DISCORD",
                payload_hash="hash",
                is_strong=True,
            )
        )
        log_repo.append(
            NotificationLogEntry(
                entry_id="log2",
                ticker="3901:TSE",
                category="データ不明",
                condition_key="UNKNOWN:eps",
                sent_at="2026-02-13T00:00:00+00:00",
                channel="DISCORD",
                payload_hash="hash2",
                is_strong=False,
            )
        )
        logs = log_repo.list_recent("3901:TSE")
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].category, "データ不明")
        self.assertEqual(log_repo.count_timeline(ticker="3901:TSE"), 2)
        ranged = log_repo.list_timeline(
            ticker="3901:TSE",
            sent_at_from="2026-02-12T12:00:00+00:00",
            sent_at_to="2026-02-14T00:00:00+00:00",
            limit=10,
            offset=0,
        )
        self.assertEqual(len(ranged), 1)
        self.assertEqual(ranged[0].entry_id, "log2")

    def test_earnings_repository(self) -> None:
        repo = FirestoreEarningsCalendarRepository(FakeFirestoreClient())
        row = EarningsCalendarEntry(
            ticker="3901:TSE",
            earnings_date="2026-02-13",
            earnings_time="15:00",
            quarter="3Q",
            source="株探",
            fetched_at="2026-02-12T00:00:00+00:00",
        )
        repo.upsert(row)
        rows = repo.list_by_ticker("3901:TSE")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].earnings_time, "15:00")


if __name__ == "__main__":
    unittest.main()

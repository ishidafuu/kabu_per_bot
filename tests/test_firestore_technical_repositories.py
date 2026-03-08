from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.storage.firestore_price_bars_daily_repository import FirestorePriceBarsDailyRepository
from kabu_per_bot.storage.firestore_technical_alert_rules_repository import FirestoreTechnicalAlertRulesRepository
from kabu_per_bot.storage.firestore_technical_alert_state_repository import FirestoreTechnicalAlertStateRepository
from kabu_per_bot.storage.firestore_technical_indicators_daily_repository import (
    FirestoreTechnicalIndicatorsDailyRepository,
)
from kabu_per_bot.storage.firestore_technical_sync_state_repository import FirestoreTechnicalSyncStateRepository
from kabu_per_bot.technical import (
    PriceBarDaily,
    TechnicalAlertOperator,
    TechnicalAlertRule,
    TechnicalAlertState,
    TechnicalIndicatorsDaily,
    TechnicalSyncState,
)


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
        del merge
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


class FirestoreTechnicalRepositoriesTest(unittest.TestCase):
    def test_price_bars_repository(self) -> None:
        repo = FirestorePriceBarsDailyRepository(FakeFirestoreClient())
        bar = PriceBarDaily(
            ticker="3901:TSE",
            trade_date="2026-03-07",
            code="3901",
            date="2026-03-07",
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
        )
        repo.upsert(bar)
        found = repo.get("3901:TSE", "2026-03-07")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.close_price, 104.0)

    def test_technical_indicators_repository(self) -> None:
        repo = FirestoreTechnicalIndicatorsDailyRepository(FakeFirestoreClient())
        row = TechnicalIndicatorsDaily(
            ticker="3901:TSE",
            trade_date="2026-03-07",
            schema_version=1,
            calculated_at="2026-03-08T00:00:00+00:00",
            values={"close_vs_ma25": 3.5, "above_ma5": True},
        )
        repo.upsert(row)
        found = repo.get("3901:TSE", "2026-03-07")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.get_value("close_vs_ma25"), 3.5)

    def test_technical_sync_state_repository(self) -> None:
        repo = FirestoreTechnicalSyncStateRepository(FakeFirestoreClient())
        row = TechnicalSyncState(
            ticker="3901:TSE",
            latest_fetched_trade_date="2026-03-07",
            latest_calculated_trade_date="2026-03-06",
            last_run_at="2026-03-08T00:00:00+00:00",
            last_status="SUCCESS",
        )
        repo.upsert(row)
        found = repo.get("3901:TSE")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.last_status, "SUCCESS")
        self.assertEqual(repo.list_recent(limit=1)[0].ticker, "3901:TSE")

    def test_technical_alert_rules_repository(self) -> None:
        repo = FirestoreTechnicalAlertRulesRepository(FakeFirestoreClient())
        rule = TechnicalAlertRule.create(
            ticker="3901:TSE",
            rule_name="25日線上抜け",
            field_key="close_vs_ma25",
            operator=TechnicalAlertOperator.GTE,
            threshold_value=0.0,
            created_at="2026-03-08T00:00:00+00:00",
            updated_at="2026-03-08T00:00:00+00:00",
            rule_id="rule-1",
        )
        repo.upsert(rule)
        found = repo.get("3901:TSE", "rule-1")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.rule_name, "25日線上抜け")
        self.assertEqual(repo.list_recent("3901:TSE", limit=1)[0].rule_id, "rule-1")

    def test_technical_alert_state_repository(self) -> None:
        repo = FirestoreTechnicalAlertStateRepository(FakeFirestoreClient())
        state = TechnicalAlertState(
            ticker="3901:TSE",
            rule_id="rule-1",
            last_evaluated_trade_date="2026-03-07",
            last_condition_met=True,
            last_triggered_at="2026-03-08T00:00:00+00:00",
            updated_at="2026-03-08T00:00:00+00:00",
        )
        repo.upsert(state)
        found = repo.get("3901:TSE", "rule-1")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertTrue(found.last_condition_met)
        self.assertEqual(repo.list_recent("3901:TSE", limit=1)[0].rule_id, "rule-1")


if __name__ == "__main__":
    unittest.main()

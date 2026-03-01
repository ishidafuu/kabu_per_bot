from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.baseline_research import BaselineResearchRecord
from kabu_per_bot.storage.firestore_baseline_research_repository import FirestoreBaselineResearchRepository
from kabu_per_bot.storage.firestore_schema import COLLECTION_BASELINE_RESEARCH


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
        if merge and self.path in self.db:
            merged = dict(self.db[self.path])
            merged.update(data)
            self.db[self.path] = merged
            return
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


@dataclass
class FakeFirestoreClient:
    db: dict[str, dict] = field(default_factory=dict)

    def collection(self, name: str) -> FakeCollectionRef:
        return FakeCollectionRef(path=name, db=self.db)


def _record() -> BaselineResearchRecord:
    return BaselineResearchRecord(
        ticker="3901:TSE",
        as_of_month="2026-03",
        raw={"snapshot": {"close_price": 1234.5}},
        structured={"source_label": "四季報"},
        summary={"business_summary": "写真・ヘルスケア"},
        source="四季報",
        reliability_score=5,
        updated_at="2026-03-01T09:00:00+00:00",
    )


class FirestoreBaselineResearchRepositoryTest(unittest.TestCase):
    def test_upsert_and_get_latest(self) -> None:
        client = FakeFirestoreClient()
        repo = FirestoreBaselineResearchRepository(client)

        row = _record()
        repo.upsert(row)
        actual = repo.get_latest("3901:tse")

        self.assertIsNotNone(actual)
        assert actual is not None
        self.assertEqual(actual.ticker, "3901:TSE")
        self.assertEqual(actual.as_of_month, "2026-03")
        self.assertEqual(actual.summary["business_summary"], "写真・ヘルスケア")
        self.assertEqual(actual.reliability_score, 5)
        self.assertIn(f"{COLLECTION_BASELINE_RESEARCH}/3901:TSE", client.db)

    def test_get_latest_returns_none_when_missing(self) -> None:
        repo = FirestoreBaselineResearchRepository(FakeFirestoreClient())
        self.assertIsNone(repo.get_latest("3901:TSE"))


if __name__ == "__main__":
    unittest.main()

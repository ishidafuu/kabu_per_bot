from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.storage.firestore_watchlist_history_repository import FirestoreWatchlistHistoryRepository
from kabu_per_bot.watchlist import WatchlistHistoryAction, WatchlistHistoryRecord


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


class FirestoreWatchlistHistoryRepositoryTest(unittest.TestCase):
    def test_append_and_list(self) -> None:
        repo = FirestoreWatchlistHistoryRepository(FakeFirestoreClient())
        first = WatchlistHistoryRecord.create(
            ticker="3901:TSE",
            action=WatchlistHistoryAction.ADD,
            acted_at="2026-02-12T00:00:00+00:00",
        )
        second = WatchlistHistoryRecord.create(
            ticker="3901:TSE",
            action=WatchlistHistoryAction.REMOVE,
            acted_at="2026-02-12T03:00:00+00:00",
            reason="監視終了",
        )
        repo.append(first)
        repo.append(second)

        records = repo.list_by_ticker("3901:TSE")
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].action, WatchlistHistoryAction.REMOVE)
        self.assertEqual(records[0].reason, "監視終了")
        self.assertEqual(records[1].action, WatchlistHistoryAction.ADD)


if __name__ == "__main__":
    unittest.main()

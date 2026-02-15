from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository
from kabu_per_bot.watchlist import (
    CreateResult,
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchlistItem,
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

    def create(self, data: dict) -> None:
        if self.path in self.db:
            raise RuntimeError("AlreadyExists")
        self.db[self.path] = dict(data)

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

    def delete(self) -> None:
        self.db.pop(self.path, None)


@dataclass
class FakeCollectionRef:
    path: str
    db: dict[str, dict] = field(default_factory=dict)

    def document(self, document_id: str) -> FakeDocumentRef:
        return FakeDocumentRef(path=f"{self.path}/{document_id}", db=self.db)

    def stream(self) -> list[FakeSnapshot]:
        prefix = f"{self.path}/"
        snapshots = []
        for key, value in self.db.items():
            if key.startswith(prefix):
                snapshots.append(FakeSnapshot(exists=True, data=dict(value)))
        return snapshots


@dataclass
class FakeFirestoreClient:
    db: dict[str, dict] = field(default_factory=dict)

    def collection(self, name: str) -> FakeCollectionRef:
        return FakeCollectionRef(path=name, db=self.db)


class FirestoreWatchlistRepositoryTest(unittest.TestCase):
    def test_crud(self) -> None:
        repo = FirestoreWatchlistRepository(FakeFirestoreClient())
        item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            created_at="2026-02-12T00:00:00+00:00",
            updated_at="2026-02-12T00:00:00+00:00",
        )

        self.assertEqual(repo.try_create(item, max_items=100), CreateResult.CREATED)
        self.assertEqual(repo.count(), 1)
        self.assertIsNotNone(repo.get("3901:TSE"))

        updated = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルムHD",
            metric_type=MetricType.PSR,
            notify_channel=NotifyChannel.OFF,
            notify_timing=NotifyTiming.AT_21,
            created_at=item.created_at,
            updated_at="2026-02-13T00:00:00+00:00",
        )
        repo.update(updated)
        fetched = repo.get("3901:TSE")
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.metric_type, MetricType.PSR)
        self.assertEqual(fetched.notify_channel, NotifyChannel.OFF)

        self.assertTrue(repo.delete("3901:TSE"))
        self.assertFalse(repo.delete("3901:TSE"))
        self.assertEqual(repo.list_all(), [])

    def test_try_create_limit_and_duplicate(self) -> None:
        repo = FirestoreWatchlistRepository(FakeFirestoreClient())
        first = WatchlistItem(
            ticker="3901:TSE",
            name="A",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
        second = WatchlistItem(
            ticker="3902:TSE",
            name="B",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )

        self.assertEqual(repo.try_create(first, max_items=1), CreateResult.CREATED)
        self.assertEqual(repo.try_create(first, max_items=1), CreateResult.DUPLICATE)
        self.assertEqual(repo.try_create(second, max_items=1), CreateResult.LIMIT_EXCEEDED)


if __name__ == "__main__":
    unittest.main()

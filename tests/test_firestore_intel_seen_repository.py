from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.intelligence import IntelEvent, IntelKind
from kabu_per_bot.storage.firestore_intel_seen_repository import FirestoreIntelSeenRepository


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


class FirestoreIntelSeenRepositoryTest(unittest.TestCase):
    def test_mark_and_exists(self) -> None:
        repo = FirestoreIntelSeenRepository(FakeFirestoreClient())
        event = IntelEvent(
            ticker="3901:TSE",
            kind=IntelKind.IR,
            title="決算資料",
            url="https://example.com/ir/1",
            published_at="2026-02-15T00:00:00+09:00",
            source_label="IRサイト",
            content="決算資料を公開",
        )
        self.assertFalse(repo.exists(event.fingerprint))
        repo.mark_seen(event, seen_at="2026-02-15T00:10:00+09:00")
        self.assertTrue(repo.exists(event.fingerprint))


if __name__ == "__main__":
    unittest.main()

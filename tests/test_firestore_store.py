from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.storage.firestore_store import FirestoreDocumentStore


class AlreadyExists(Exception):
    pass


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

    def collection(self, name: str) -> "FakeCollectionRef":
        return FakeCollectionRef(path=f"{self.path}/{name}", db=self.db)

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

    def create(self, data: dict) -> None:
        if self.path in self.db:
            raise AlreadyExists("already exists")
        self.db[self.path] = dict(data)

    def delete(self) -> None:
        self.db.pop(self.path, None)


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


class FirestoreDocumentStoreTest(unittest.TestCase):
    def test_get_and_set_document(self) -> None:
        store = FirestoreDocumentStore(FakeFirestoreClient())

        store.set_document("watchlist/3901:TSE", {"ticker": "3901:TSE"})
        found = store.get_document("watchlist/3901:TSE")

        self.assertEqual(found, {"ticker": "3901:TSE"})

    def test_invalid_path_raises(self) -> None:
        store = FirestoreDocumentStore(FakeFirestoreClient())
        with self.assertRaises(ValueError):
            store.get_document("watchlist")

    def test_create_document(self) -> None:
        store = FirestoreDocumentStore(FakeFirestoreClient())
        first = store.create_document("watchlist/3901:TSE", {"ticker": "3901:TSE"})
        second = store.create_document("watchlist/3901:TSE", {"ticker": "3901:TSE"})

        self.assertTrue(first)
        self.assertFalse(second)

    def test_delete_document(self) -> None:
        store = FirestoreDocumentStore(FakeFirestoreClient())
        store.set_document("watchlist/3901:TSE", {"ticker": "3901:TSE"})
        store.delete_document("watchlist/3901:TSE")

        self.assertIsNone(store.get_document("watchlist/3901:TSE"))


if __name__ == "__main__":
    unittest.main()

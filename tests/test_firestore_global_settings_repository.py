from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.runtime_settings import GlobalRuntimeSettings
from kabu_per_bot.storage.firestore_global_settings_repository import (
    FirestoreGlobalSettingsRepository,
    GLOBAL_SETTINGS_DOC_ID,
)
from kabu_per_bot.storage.firestore_schema import COLLECTION_GLOBAL_SETTINGS


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


class FirestoreGlobalSettingsRepositoryTest(unittest.TestCase):
    def test_get_returns_empty_when_not_exists(self) -> None:
        repo = FirestoreGlobalSettingsRepository(FakeFirestoreClient())
        self.assertEqual(repo.get_global_settings(), GlobalRuntimeSettings())

    def test_upsert_and_get(self) -> None:
        client = FakeFirestoreClient()
        repo = FirestoreGlobalSettingsRepository(client)
        repo.upsert_global_settings(
            cooldown_hours=4,
            updated_at="2026-02-18T12:00:00+09:00",
            updated_by="admin-user",
        )

        result = repo.get_global_settings()
        self.assertEqual(result.cooldown_hours, 4)
        self.assertEqual(result.updated_by, "admin-user")
        self.assertEqual(result.updated_at, "2026-02-18T03:00:00+00:00")
        self.assertIn(f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}", client.db)

    def test_get_raises_for_invalid_cooldown_hours(self) -> None:
        client = FakeFirestoreClient(
            db={
                f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}": {
                    "cooldown_hours": 0,
                }
            }
        )
        repo = FirestoreGlobalSettingsRepository(client)
        with self.assertRaises(ValueError):
            repo.get_global_settings()


if __name__ == "__main__":
    unittest.main()

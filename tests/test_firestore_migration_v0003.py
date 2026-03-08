from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.storage.firestore_migration import COLLECTION_REGISTRY_PATH, META_SCHEMA_DOC_PATH
from kabu_per_bot.storage.firestore_migration_v0003 import (
    MIGRATION_DOC_PATH_V0003,
    MIGRATION_LOCK_DOC_PATH_V0003,
    SCHEMA_VERSION_V0003,
    apply_v0003_migration,
    build_v0003_migration_operations,
)
from kabu_per_bot.storage.firestore_schema import COLLECTION_TECHNICAL_PROFILES
from kabu_per_bot.storage.firestore_technical_profiles_seed import (
    SYSTEM_TECHNICAL_PROFILES,
    TECHNICAL_PROFILE_SEED_DOC_PATH,
    apply_system_technical_profile_seed,
    build_system_technical_profiles,
)


@dataclass
class InMemoryStore:
    docs: dict[str, dict] = field(default_factory=dict)

    def get_document(self, path: str) -> dict | None:
        return self.docs.get(path)

    def set_document(self, path: str, data: dict, *, merge: bool = False) -> None:
        if merge and path in self.docs:
            merged = dict(self.docs[path])
            merged.update(data)
            self.docs[path] = merged
            return
        self.docs[path] = dict(data)

    def create_document(self, path: str, data: dict) -> bool:
        if path in self.docs:
            return False
        self.docs[path] = dict(data)
        return True

    def delete_document(self, path: str) -> None:
        self.docs.pop(path, None)


class FirestoreMigrationV0003Test(unittest.TestCase):
    def test_build_operations_contains_technical_profiles_collection(self) -> None:
        operations = build_v0003_migration_operations("2026-03-08T00:00:00+00:00")
        self.assertEqual(len(operations), 3)
        self.assertEqual(operations[1].path, f"{COLLECTION_REGISTRY_PATH}/{COLLECTION_TECHNICAL_PROFILES}")
        self.assertEqual(operations[-1].path, MIGRATION_DOC_PATH_V0003)

    def test_apply_migration_once(self) -> None:
        store = InMemoryStore(
            docs={
                META_SCHEMA_DOC_PATH: {
                    "current_schema_version": 2,
                    "updated_at": "2026-03-08T00:00:00+00:00",
                }
            }
        )

        first = apply_v0003_migration(store, applied_at="2026-03-09T00:00:00+00:00")
        second = apply_v0003_migration(store, applied_at="2026-03-09T01:00:00+00:00")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertIn(MIGRATION_DOC_PATH_V0003, store.docs)
        self.assertNotIn(MIGRATION_LOCK_DOC_PATH_V0003, store.docs)
        self.assertEqual(store.docs[META_SCHEMA_DOC_PATH]["current_schema_version"], SCHEMA_VERSION_V0003)

    def test_system_profile_seed_is_idempotent(self) -> None:
        store = InMemoryStore()

        first = apply_system_technical_profile_seed(store, applied_at="2026-03-09T00:00:00+00:00")
        second = apply_system_technical_profile_seed(store, applied_at="2026-03-09T01:00:00+00:00")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertIn(TECHNICAL_PROFILE_SEED_DOC_PATH, store.docs)
        for row in SYSTEM_TECHNICAL_PROFILES:
            self.assertIn(f"{COLLECTION_TECHNICAL_PROFILES}/{row['profile_id']}", store.docs)

    def test_build_system_profiles_applies_timestamps(self) -> None:
        rows = build_system_technical_profiles("2026-03-09T00:00:00+00:00")

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["created_at"], "2026-03-09T00:00:00+00:00")
        self.assertEqual(rows[0]["updated_at"], "2026-03-09T00:00:00+00:00")
        self.assertEqual(rows[2]["profile_key"], "value_dividend")


if __name__ == "__main__":
    unittest.main()

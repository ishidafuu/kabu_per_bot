from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.storage.firestore_migration import COLLECTION_REGISTRY_PATH, META_SCHEMA_DOC_PATH
from kabu_per_bot.storage.firestore_migration_v0002 import (
    MIGRATION_DOC_PATH_V0002,
    MIGRATION_LOCK_DOC_PATH_V0002,
    SCHEMA_VERSION_V0002,
    TECHNICAL_COLLECTIONS_V0002,
    apply_v0002_migration,
    build_v0002_migration_operations,
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


class FirestoreMigrationV0002Test(unittest.TestCase):
    def test_build_operations_contains_all_technical_collections(self) -> None:
        operations = build_v0002_migration_operations("2026-03-08T00:00:00+00:00")
        self.assertEqual(len(operations), len(TECHNICAL_COLLECTIONS_V0002) + 2)
        self.assertEqual(operations[-1].path, MIGRATION_DOC_PATH_V0002)

    def test_apply_migration_once(self) -> None:
        store = InMemoryStore(
            docs={
                META_SCHEMA_DOC_PATH: {
                    "current_schema_version": 1,
                    "updated_at": "2026-02-12T00:00:00+00:00",
                }
            }
        )

        first = apply_v0002_migration(store, applied_at="2026-03-08T00:00:00+00:00")
        second = apply_v0002_migration(store, applied_at="2026-03-08T01:00:00+00:00")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertIn(MIGRATION_DOC_PATH_V0002, store.docs)
        self.assertNotIn(MIGRATION_LOCK_DOC_PATH_V0002, store.docs)
        self.assertEqual(
            store.docs[META_SCHEMA_DOC_PATH]["current_schema_version"],
            SCHEMA_VERSION_V0002,
        )

    def test_lock_contention_returns_false(self) -> None:
        store = InMemoryStore(
            docs={
                MIGRATION_LOCK_DOC_PATH_V0002: {
                    "id": "0002_technical_indicators",
                    "status": "running",
                    "started_at": "2026-03-08T00:00:00+00:00",
                }
            }
        )
        result = apply_v0002_migration(store, applied_at="2026-03-08T01:00:00+00:00")

        self.assertFalse(result)
        self.assertNotIn(MIGRATION_DOC_PATH_V0002, store.docs)

    def test_migration_marker_written_after_collection_registry(self) -> None:
        store = InMemoryStore()
        apply_v0002_migration(store, applied_at="2026-03-08T00:00:00+00:00")

        migration_doc = store.docs[MIGRATION_DOC_PATH_V0002]
        self.assertEqual(migration_doc["status"], "completed")
        for collection_name in TECHNICAL_COLLECTIONS_V0002:
            registry_path = f"{COLLECTION_REGISTRY_PATH}/{collection_name}"
            self.assertIn(registry_path, store.docs)


if __name__ == "__main__":
    unittest.main()

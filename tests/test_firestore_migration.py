from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.storage.firestore_migration import (
    COLLECTION_REGISTRY_PATH,
    MIGRATION_DOC_PATH,
    MIGRATION_LOCK_DOC_PATH,
    apply_initial_migration,
    build_initial_migration_operations,
)
from kabu_per_bot.storage.firestore_schema import ALL_COLLECTIONS


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


class FirestoreMigrationTest(unittest.TestCase):
    def test_build_operations_contains_all_collections(self) -> None:
        operations = build_initial_migration_operations("2026-02-12T00:00:00+00:00")
        self.assertEqual(len(operations), len(ALL_COLLECTIONS) + 2)
        self.assertEqual(operations[-1].path, MIGRATION_DOC_PATH)

    def test_apply_migration_once(self) -> None:
        store = InMemoryStore()
        first = apply_initial_migration(store, applied_at="2026-02-12T00:00:00+00:00")
        second = apply_initial_migration(store, applied_at="2026-02-12T01:00:00+00:00")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertIn(MIGRATION_DOC_PATH, store.docs)
        self.assertNotIn(MIGRATION_LOCK_DOC_PATH, store.docs)

    def test_lock_contention_returns_false(self) -> None:
        store = InMemoryStore(
            docs={
                MIGRATION_LOCK_DOC_PATH: {
                    "id": "0001_initial",
                    "status": "running",
                    "started_at": "2026-02-12T00:00:00+00:00",
                }
            }
        )
        result = apply_initial_migration(store, applied_at="2026-02-12T01:00:00+00:00")

        self.assertFalse(result)
        self.assertNotIn(MIGRATION_DOC_PATH, store.docs)

    def test_migration_marker_written_after_collection_registry(self) -> None:
        store = InMemoryStore()
        apply_initial_migration(store, applied_at="2026-02-12T00:00:00+00:00")

        migration_doc = store.docs[MIGRATION_DOC_PATH]
        self.assertEqual(migration_doc["status"], "completed")
        for collection_name in ALL_COLLECTIONS:
            registry_path = f"{COLLECTION_REGISTRY_PATH}/{collection_name}"
            self.assertIn(registry_path, store.docs)


if __name__ == "__main__":
    unittest.main()

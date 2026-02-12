from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.storage.firestore_migration import (
    MIGRATION_DOC_PATH,
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


class FirestoreMigrationTest(unittest.TestCase):
    def test_build_operations_contains_all_collections(self) -> None:
        operations = build_initial_migration_operations("2026-02-12T00:00:00+00:00")
        self.assertEqual(len(operations), len(ALL_COLLECTIONS) + 2)

    def test_apply_migration_once(self) -> None:
        store = InMemoryStore()
        first = apply_initial_migration(store, applied_at="2026-02-12T00:00:00+00:00")
        second = apply_initial_migration(store, applied_at="2026-02-12T01:00:00+00:00")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertIn(MIGRATION_DOC_PATH, store.docs)


if __name__ == "__main__":
    unittest.main()


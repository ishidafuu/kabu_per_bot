from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from kabu_per_bot.storage.firestore_schema import (
    ALL_COLLECTIONS,
    MIGRATION_ID,
    SCHEMA_VERSION,
)


META_SCHEMA_DOC_PATH = "_meta/schema"
MIGRATIONS_COLLECTION_PATH = f"{META_SCHEMA_DOC_PATH}/migrations"
COLLECTION_REGISTRY_PATH = f"{META_SCHEMA_DOC_PATH}/collections"
MIGRATION_DOC_PATH = f"{MIGRATIONS_COLLECTION_PATH}/{MIGRATION_ID}"
MIGRATION_LOCK_DOC_PATH = f"{MIGRATIONS_COLLECTION_PATH}/{MIGRATION_ID}_lock"


@dataclass(frozen=True)
class MigrationOperation:
    path: str
    data: dict[str, Any]
    merge: bool = False


class DocumentStore(Protocol):
    def get_document(self, path: str) -> Mapping[str, Any] | None:
        """Get document data. Return None when the document does not exist."""

    def set_document(self, path: str, data: Mapping[str, Any], *, merge: bool = False) -> None:
        """Set document data."""

    def create_document(self, path: str, data: Mapping[str, Any]) -> bool:
        """Create document atomically.

        Returns False when document already exists.
        """

    def delete_document(self, path: str) -> None:
        """Delete document. No-op when document does not exist."""


def build_initial_migration_operations(applied_at: str) -> list[MigrationOperation]:
    ops: list[MigrationOperation] = [
        MigrationOperation(
            path=META_SCHEMA_DOC_PATH,
            data={
                "current_schema_version": SCHEMA_VERSION,
                "updated_at": applied_at,
            },
            merge=True,
        ),
    ]
    for collection_name in ALL_COLLECTIONS:
        ops.append(
            MigrationOperation(
                path=f"{COLLECTION_REGISTRY_PATH}/{collection_name}",
                data={
                    "name": collection_name,
                    "created_by_migration": MIGRATION_ID,
                    "schema_version": SCHEMA_VERSION,
                    "created_at": applied_at,
                },
            )
        )
    # Completion marker must be written last.
    ops.append(
        MigrationOperation(
            path=MIGRATION_DOC_PATH,
            data={
                "id": MIGRATION_ID,
                "schema_version": SCHEMA_VERSION,
                "applied_at": applied_at,
                "status": "completed",
            },
        )
    )
    return ops


def apply_initial_migration(store: DocumentStore, *, applied_at: str) -> bool:
    """Apply schema v1 migration once.

    Returns True if applied in this run, False if already applied.
    """

    existing = store.get_document(MIGRATION_DOC_PATH)
    if existing is not None:
        return False

    lock_acquired = store.create_document(
        MIGRATION_LOCK_DOC_PATH,
        {
            "id": MIGRATION_ID,
            "status": "running",
            "started_at": applied_at,
        },
    )
    if not lock_acquired:
        return False

    try:
        # Re-check after lock acquisition to avoid duplicate apply under race.
        if store.get_document(MIGRATION_DOC_PATH) is not None:
            return False
        for op in build_initial_migration_operations(applied_at):
            store.set_document(op.path, op.data, merge=op.merge)
        return True
    finally:
        store.delete_document(MIGRATION_LOCK_DOC_PATH)

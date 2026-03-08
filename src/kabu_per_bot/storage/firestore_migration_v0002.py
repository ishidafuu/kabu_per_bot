from __future__ import annotations

from kabu_per_bot.storage.firestore_migration import (
    COLLECTION_REGISTRY_PATH,
    META_SCHEMA_DOC_PATH,
    MIGRATIONS_COLLECTION_PATH,
    DocumentStore,
    MigrationOperation,
)
from kabu_per_bot.storage.firestore_schema import TECHNICAL_COLLECTIONS


SCHEMA_VERSION_V0002 = 2
MIGRATION_ID_V0002 = "0002_technical_indicators"
MIGRATION_DOC_PATH_V0002 = f"{MIGRATIONS_COLLECTION_PATH}/{MIGRATION_ID_V0002}"
MIGRATION_LOCK_DOC_PATH_V0002 = f"{MIGRATIONS_COLLECTION_PATH}/{MIGRATION_ID_V0002}_lock"

TECHNICAL_COLLECTIONS_V0002 = TECHNICAL_COLLECTIONS


def build_v0002_migration_operations(applied_at: str) -> list[MigrationOperation]:
    ops: list[MigrationOperation] = [
        MigrationOperation(
            path=META_SCHEMA_DOC_PATH,
            data={
                "current_schema_version": SCHEMA_VERSION_V0002,
                "updated_at": applied_at,
            },
            merge=True,
        ),
    ]
    for collection_name in TECHNICAL_COLLECTIONS_V0002:
        ops.append(
            MigrationOperation(
                path=f"{COLLECTION_REGISTRY_PATH}/{collection_name}",
                data={
                    "name": collection_name,
                    "created_by_migration": MIGRATION_ID_V0002,
                    "schema_version": SCHEMA_VERSION_V0002,
                    "created_at": applied_at,
                },
            )
        )
    ops.append(
        MigrationOperation(
            path=MIGRATION_DOC_PATH_V0002,
            data={
                "id": MIGRATION_ID_V0002,
                "schema_version": SCHEMA_VERSION_V0002,
                "applied_at": applied_at,
                "status": "completed",
            },
        )
    )
    return ops


def apply_v0002_migration(store: DocumentStore, *, applied_at: str) -> bool:
    existing = store.get_document(MIGRATION_DOC_PATH_V0002)
    if existing is not None:
        return False

    lock_acquired = store.create_document(
        MIGRATION_LOCK_DOC_PATH_V0002,
        {
            "id": MIGRATION_ID_V0002,
            "status": "running",
            "started_at": applied_at,
        },
    )
    if not lock_acquired:
        return False

    try:
        if store.get_document(MIGRATION_DOC_PATH_V0002) is not None:
            return False
        for op in build_v0002_migration_operations(applied_at):
            store.set_document(op.path, op.data, merge=op.merge)
        return True
    finally:
        store.delete_document(MIGRATION_LOCK_DOC_PATH_V0002)

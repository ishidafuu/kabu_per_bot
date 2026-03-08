from __future__ import annotations

from kabu_per_bot.storage.firestore_migration import (
    COLLECTION_REGISTRY_PATH,
    META_SCHEMA_DOC_PATH,
    MIGRATIONS_COLLECTION_PATH,
    DocumentStore,
    MigrationOperation,
)
from kabu_per_bot.storage.firestore_schema import COLLECTION_TECHNICAL_PROFILES


SCHEMA_VERSION_V0003 = 3
MIGRATION_ID_V0003 = "0003_technical_profiles"
MIGRATION_DOC_PATH_V0003 = f"{MIGRATIONS_COLLECTION_PATH}/{MIGRATION_ID_V0003}"
MIGRATION_LOCK_DOC_PATH_V0003 = f"{MIGRATIONS_COLLECTION_PATH}/{MIGRATION_ID_V0003}_lock"


def build_v0003_migration_operations(applied_at: str) -> list[MigrationOperation]:
    return [
        MigrationOperation(
            path=META_SCHEMA_DOC_PATH,
            data={
                "current_schema_version": SCHEMA_VERSION_V0003,
                "updated_at": applied_at,
            },
            merge=True,
        ),
        MigrationOperation(
            path=f"{COLLECTION_REGISTRY_PATH}/{COLLECTION_TECHNICAL_PROFILES}",
            data={
                "name": COLLECTION_TECHNICAL_PROFILES,
                "created_by_migration": MIGRATION_ID_V0003,
                "schema_version": SCHEMA_VERSION_V0003,
                "created_at": applied_at,
            },
        ),
        MigrationOperation(
            path=MIGRATION_DOC_PATH_V0003,
            data={
                "id": MIGRATION_ID_V0003,
                "schema_version": SCHEMA_VERSION_V0003,
                "applied_at": applied_at,
                "status": "completed",
            },
        ),
    ]


def apply_v0003_migration(store: DocumentStore, *, applied_at: str) -> bool:
    existing = store.get_document(MIGRATION_DOC_PATH_V0003)
    if existing is not None:
        return False

    lock_acquired = store.create_document(
        MIGRATION_LOCK_DOC_PATH_V0003,
        {
            "id": MIGRATION_ID_V0003,
            "status": "running",
            "started_at": applied_at,
        },
    )
    if not lock_acquired:
        return False

    try:
        if store.get_document(MIGRATION_DOC_PATH_V0003) is not None:
            return False
        for op in build_v0003_migration_operations(applied_at):
            store.set_document(op.path, op.data, merge=op.merge)
        return True
    finally:
        store.delete_document(MIGRATION_LOCK_DOC_PATH_V0003)

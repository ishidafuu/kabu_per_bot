#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import sys

from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_migration_v0003 import apply_v0003_migration
from kabu_per_bot.storage.firestore_store import FirestoreDocumentStore
from kabu_per_bot.storage.firestore_technical_profiles_seed import apply_system_technical_profile_seed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply Firestore schema migration v0003 for technical profiles and seed system profiles."
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Firestore project id. If omitted, FIRESTORE_PROJECT_ID from settings is used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    project_id = (args.project_id or settings.firestore_project_id).strip()
    if not project_id:
        print(
            "Firestore project id is required. Set --project-id or FIRESTORE_PROJECT_ID.",
            file=sys.stderr,
        )
        return 2

    try:
        from google.cloud import firestore
    except ModuleNotFoundError:
        print("google-cloud-firestore is not installed. Install with: pip install '.[gcp]'", file=sys.stderr)
        return 1

    client = firestore.Client(project=project_id)
    store = FirestoreDocumentStore(client)
    applied_at = datetime.now(timezone.utc).isoformat()
    migration_applied = apply_v0003_migration(store, applied_at=applied_at)
    seed_applied = apply_system_technical_profile_seed(store, applied_at=applied_at)

    if migration_applied:
        print("Applied Firestore migration 0003_technical_profiles")
    else:
        print("Firestore migration 0003_technical_profiles was already applied")

    if seed_applied:
        print("Seeded technical profile system defaults")
    else:
        print("Technical profile system defaults were already seeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

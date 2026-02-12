#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import os
import sys

from kabu_per_bot.storage.firestore_migration import apply_initial_migration
from kabu_per_bot.storage.firestore_store import FirestoreDocumentStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Firestore schema migration v0001.")
    parser.add_argument(
        "--project-id",
        default=os.getenv("FIRESTORE_PROJECT_ID", "").strip() or None,
        help="Firestore project id. Defaults to FIRESTORE_PROJECT_ID.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        from google.cloud import firestore
    except ModuleNotFoundError:
        print("google-cloud-firestore is not installed. Install with: pip install '.[gcp]'", file=sys.stderr)
        return 1

    client = firestore.Client(project=args.project_id)
    store = FirestoreDocumentStore(client)
    applied = apply_initial_migration(
        store,
        applied_at=datetime.now(timezone.utc).isoformat(),
    )
    if applied:
        print("Applied Firestore migration 0001_initial")
    else:
        print("Firestore migration 0001_initial was already applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


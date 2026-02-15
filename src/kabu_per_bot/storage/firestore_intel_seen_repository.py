from __future__ import annotations

from typing import Any

from kabu_per_bot.intelligence import IntelEvent
from kabu_per_bot.storage.firestore_schema import COLLECTION_INTEL_SEEN


class FirestoreIntelSeenRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_INTEL_SEEN)

    def exists(self, fingerprint: str) -> bool:
        snapshot = self._collection.document(fingerprint).get()
        return bool(snapshot.exists)

    def mark_seen(self, event: IntelEvent, *, seen_at: str) -> None:
        self._collection.document(event.fingerprint).set(
            {
                "id": event.fingerprint,
                "ticker": event.ticker,
                "kind": event.kind.value,
                "title": event.title,
                "url": event.url,
                "published_at": event.published_at,
                "source_label": event.source_label,
                "seen_at": seen_at,
            },
            merge=False,
        )

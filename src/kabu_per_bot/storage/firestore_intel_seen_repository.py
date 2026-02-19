from __future__ import annotations

from typing import Any

from kabu_per_bot.intelligence import IntelEvent
from kabu_per_bot.storage.firestore_schema import COLLECTION_INTEL_SEEN, normalize_ticker


class FirestoreIntelSeenRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_INTEL_SEEN)

    def exists(self, fingerprint: str) -> bool:
        snapshot = self._collection.document(fingerprint).get()
        return bool(snapshot.exists)

    def has_any_for_ticker(self, ticker: str) -> bool:
        normalized_ticker = normalize_ticker(ticker)
        if hasattr(self._collection, "where"):
            query = self._collection.where("ticker", "==", normalized_ticker)
            if hasattr(query, "limit"):
                query = query.limit(1)
            for _ in query.stream():
                return True
            return False
        if hasattr(self._collection, "stream"):
            for snapshot in self._collection.stream():
                data = snapshot.to_dict() or {}
                if str(data.get("ticker", "")).strip().upper() == normalized_ticker:
                    return True
        return False

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

    def reset_sns_seen(self, *, ticker: str | None = None) -> int:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        targets: list[Any] = []
        if hasattr(self._collection, "where"):
            query = self._collection.where("kind", "==", "SNS")
            if normalized_ticker:
                query = query.where("ticker", "==", normalized_ticker)
            targets = list(query.stream())
        if not targets:
            for snapshot in self._collection.stream():
                data = snapshot.to_dict() or {}
                if str(data.get("kind", "")).strip().upper() != "SNS":
                    continue
                if normalized_ticker and str(data.get("ticker", "")).strip().upper() != normalized_ticker:
                    continue
                targets.append(snapshot)

        deleted = 0
        for snapshot in targets:
            snapshot.reference.delete()
            deleted += 1
        return deleted

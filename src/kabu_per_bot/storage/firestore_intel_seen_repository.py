from __future__ import annotations

import logging
from typing import Any

from kabu_per_bot.intelligence import IntelEvent, IntelKind
from kabu_per_bot.storage.firestore_schema import COLLECTION_INTEL_SEEN, normalize_ticker


LOGGER = logging.getLogger(__name__)


class FirestoreIntelSeenRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_INTEL_SEEN)

    def exists(self, fingerprint: str) -> bool:
        snapshot = self._collection.document(fingerprint).get()
        return bool(snapshot.exists)

    def has_any_for_ticker(self, ticker: str) -> bool:
        normalized_ticker = normalize_ticker(ticker)
        return self._has_any(ticker=normalized_ticker)

    def has_any_for_ticker_and_kind(self, ticker: str, kind: IntelKind | str) -> bool:
        normalized_ticker = normalize_ticker(ticker)
        normalized_kind = kind.value if isinstance(kind, IntelKind) else str(kind).strip().upper()
        return self._has_any(ticker=normalized_ticker, kind=normalized_kind)

    def _has_any(self, *, ticker: str, kind: str | None = None) -> bool:
        if hasattr(self._collection, "where"):
            try:
                query = self._collection.where("ticker", "==", ticker)
                if kind is not None:
                    query = query.where("kind", "==", kind)
                if hasattr(query, "limit"):
                    query = query.limit(1)
                for _ in query.stream():
                    return True
                return False
            except Exception as exc:
                LOGGER.warning("intel_seen query失敗のためフォールバック: %s", exc)
        if hasattr(self._collection, "stream"):
            for snapshot in self._collection.stream():
                data = snapshot.to_dict() or {}
                if str(data.get("ticker", "")).strip().upper() != ticker:
                    continue
                if kind is not None and str(data.get("kind", "")).strip().upper() != kind:
                    continue
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
            try:
                query = self._collection.where("kind", "==", "SNS")
                if normalized_ticker:
                    query = query.where("ticker", "==", normalized_ticker)
                targets = list(query.stream())
            except Exception as exc:
                LOGGER.warning("intel_seen reset query失敗のためフォールバック: %s", exc)
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

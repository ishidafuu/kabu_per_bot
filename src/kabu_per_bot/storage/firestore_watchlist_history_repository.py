from __future__ import annotations

from typing import Any

from kabu_per_bot.storage.firestore_schema import COLLECTION_WATCHLIST_HISTORY, normalize_ticker
from kabu_per_bot.watchlist import WatchlistHistoryRecord


class FirestoreWatchlistHistoryRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_WATCHLIST_HISTORY)

    def append(self, record: WatchlistHistoryRecord) -> None:
        self._collection.document(record.record_id).set(record.to_document(), merge=False)

    def list_by_ticker(self, ticker: str, *, limit: int = 100) -> list[WatchlistHistoryRecord]:
        return self.list_timeline(ticker=ticker, limit=limit)

    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[WatchlistHistoryRecord]:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        if hasattr(self._collection, "where") and hasattr(self._collection, "order_by"):
            query = self._collection
            if normalized_ticker:
                query = query.where("ticker", "==", normalized_ticker)
            query = query.order_by("acted_at", direction="DESCENDING")
            if offset > 0 and hasattr(query, "offset"):
                query = query.offset(offset)
            if limit is not None and hasattr(query, "limit"):
                query = query.limit(limit)
            return [WatchlistHistoryRecord.from_document(snapshot.to_dict() or {}) for snapshot in query.stream()]

        records: list[WatchlistHistoryRecord] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if normalized_ticker and str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            records.append(WatchlistHistoryRecord.from_document(data))
        records.sort(key=lambda record: record.acted_at, reverse=True)
        if limit is None:
            return records[offset:]
        return records[offset : offset + limit]

    def count_timeline(
        self,
        *,
        ticker: str | None = None,
    ) -> int:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        if hasattr(self._collection, "where"):
            query = self._collection
            if normalized_ticker:
                query = query.where("ticker", "==", normalized_ticker)
            return sum(1 for _ in query.stream())

        count = 0
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if normalized_ticker and str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            count += 1
        return count

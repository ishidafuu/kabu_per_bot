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
        normalized_ticker = normalize_ticker(ticker)
        records: list[WatchlistHistoryRecord] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            records.append(WatchlistHistoryRecord.from_document(data))
        records.sort(key=lambda record: record.acted_at, reverse=True)
        return records[:limit]

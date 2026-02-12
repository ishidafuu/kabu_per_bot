from __future__ import annotations

from typing import Any

from kabu_per_bot.storage.firestore_schema import COLLECTION_WATCHLIST, normalize_ticker
from kabu_per_bot.watchlist import WatchlistItem


class FirestoreWatchlistRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_WATCHLIST)

    def count(self) -> int:
        return sum(1 for _ in self._collection.stream())

    def get(self, ticker: str) -> WatchlistItem | None:
        doc_id = normalize_ticker(ticker)
        snapshot = self._collection.document(doc_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        return WatchlistItem.from_document(data)

    def list_all(self) -> list[WatchlistItem]:
        items = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            items.append(WatchlistItem.from_document(data))
        return sorted(items, key=lambda item: item.ticker)

    def create(self, item: WatchlistItem) -> None:
        self._collection.document(item.ticker).create(item.to_document())

    def update(self, item: WatchlistItem) -> None:
        self._collection.document(item.ticker).set(item.to_document(), merge=False)

    def delete(self, ticker: str) -> bool:
        doc_id = normalize_ticker(ticker)
        ref = self._collection.document(doc_id)
        snapshot = ref.get()
        if not snapshot.exists:
            return False
        ref.delete()
        return True


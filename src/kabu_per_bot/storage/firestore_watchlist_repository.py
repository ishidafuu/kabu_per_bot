from __future__ import annotations

from typing import Any

from kabu_per_bot.storage.firestore_schema import COLLECTION_WATCHLIST, normalize_ticker
from kabu_per_bot.watchlist import CreateResult, WatchlistItem


class FirestoreWatchlistRepository:
    def __init__(self, client: Any) -> None:
        self._client = client
        self._collection = client.collection(COLLECTION_WATCHLIST)

    def try_create(self, item: WatchlistItem, *, max_items: int) -> CreateResult:
        if max_items <= 0:
            raise ValueError("max_items must be > 0.")

        try:
            from google.cloud import firestore
        except ModuleNotFoundError:
            return self._try_create_fallback(item, max_items=max_items)

        if not hasattr(self._client, "transaction"):
            return self._try_create_fallback(item, max_items=max_items)

        doc_ref = self._collection.document(item.ticker)
        transaction = self._client.transaction()

        @firestore.transactional
        def _transactional_create(tx: Any) -> CreateResult:
            snapshot = doc_ref.get(transaction=tx)
            if snapshot.exists:
                return CreateResult.DUPLICATE

            count = 0
            for _ in self._collection.limit(max_items).stream(transaction=tx):
                count += 1
            if count >= max_items:
                return CreateResult.LIMIT_EXCEEDED

            tx.create(doc_ref, item.to_document())
            return CreateResult.CREATED

        return _transactional_create(transaction)

    def _try_create_fallback(self, item: WatchlistItem, *, max_items: int) -> CreateResult:
        doc_ref = self._collection.document(item.ticker)
        snapshot = doc_ref.get()
        if snapshot.exists:
            return CreateResult.DUPLICATE
        if self.count() >= max_items:
            return CreateResult.LIMIT_EXCEEDED
        try:
            doc_ref.create(item.to_document())
        except Exception as exc:
            if exc.__class__.__name__ in {"AlreadyExists", "Conflict"}:
                return CreateResult.DUPLICATE
            raise
        return CreateResult.CREATED

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

from __future__ import annotations

from typing import Any

from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.storage.firestore_schema import COLLECTION_NOTIFICATION_LOG, normalize_ticker


class FirestoreNotificationLogRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_NOTIFICATION_LOG)

    def append(self, entry: NotificationLogEntry) -> None:
        self._collection.document(entry.entry_id).set(entry.to_document(), merge=False)

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        normalized_ticker = normalize_ticker(ticker)
        rows: list[NotificationLogEntry] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            rows.append(NotificationLogEntry.from_document(data))
        rows.sort(key=lambda row: row.sent_at, reverse=True)
        return rows[:limit]

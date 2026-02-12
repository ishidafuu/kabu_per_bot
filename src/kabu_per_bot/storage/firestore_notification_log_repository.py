from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.storage.firestore_schema import COLLECTION_NOTIFICATION_LOG, normalize_ticker


class FirestoreNotificationLogRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_NOTIFICATION_LOG)

    def append(self, entry: NotificationLogEntry) -> None:
        self._collection.document(entry.entry_id).set(entry.to_document(), merge=False)

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        return self.list_timeline(ticker=ticker, limit=limit)

    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> list[NotificationLogEntry]:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        from_dt = _parse_iso_datetime(sent_at_from) if sent_at_from else None
        to_dt = _parse_iso_datetime(sent_at_to) if sent_at_to else None
        if hasattr(self._collection, "where") and hasattr(self._collection, "order_by"):
            query = self._collection
            if normalized_ticker:
                query = query.where("ticker", "==", normalized_ticker)
            if sent_at_from is not None:
                query = query.where("sent_at", ">=", sent_at_from)
            if sent_at_to is not None:
                query = query.where("sent_at", "<", sent_at_to)
            query = query.order_by("sent_at", direction="DESCENDING")
            if offset > 0 and hasattr(query, "offset"):
                query = query.offset(offset)
            if limit is not None and hasattr(query, "limit"):
                query = query.limit(limit)
            return [NotificationLogEntry.from_document(snapshot.to_dict() or {}) for snapshot in query.stream()]

        rows: list[NotificationLogEntry] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if normalized_ticker and str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            row = NotificationLogEntry.from_document(data)
            sent_at = _parse_iso_datetime(row.sent_at)
            if from_dt is not None and sent_at < from_dt:
                continue
            if to_dt is not None and sent_at >= to_dt:
                continue
            rows.append(row)
        rows.sort(key=lambda row: _parse_iso_datetime(row.sent_at), reverse=True)
        if limit is None:
            return rows[offset:]
        return rows[offset : offset + limit]

    def count_timeline(
        self,
        *,
        ticker: str | None = None,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> int:
        normalized_ticker = normalize_ticker(ticker) if ticker is not None else None
        from_dt = _parse_iso_datetime(sent_at_from) if sent_at_from else None
        to_dt = _parse_iso_datetime(sent_at_to) if sent_at_to else None
        if hasattr(self._collection, "where"):
            query = self._collection
            if normalized_ticker:
                query = query.where("ticker", "==", normalized_ticker)
            if sent_at_from is not None:
                query = query.where("sent_at", ">=", sent_at_from)
            if sent_at_to is not None:
                query = query.where("sent_at", "<", sent_at_to)
            return sum(1 for _ in query.stream())

        count = 0
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if normalized_ticker and str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            sent_at_raw = data.get("sent_at")
            if sent_at_raw is None:
                continue
            sent_at = _parse_iso_datetime(str(sent_at_raw))
            if from_dt is not None and sent_at < from_dt:
                continue
            if to_dt is not None and sent_at >= to_dt:
                continue
            count += 1
        return count

    def failed_job_exists(
        self,
        *,
        sent_at_from: str,
        sent_at_to: str,
    ) -> bool | None:
        # 現時点では job 実行結果を保持する専用ストアがないため判定不能。
        return None


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed

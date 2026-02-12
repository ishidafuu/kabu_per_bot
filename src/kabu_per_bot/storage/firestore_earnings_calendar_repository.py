from __future__ import annotations

from typing import Any

from kabu_per_bot.earnings import EarningsCalendarEntry
from kabu_per_bot.storage.firestore_schema import (
    COLLECTION_EARNINGS_CALENDAR,
    earnings_calendar_doc_id,
    normalize_ticker,
)


class FirestoreEarningsCalendarRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_EARNINGS_CALENDAR)

    def upsert(self, entry: EarningsCalendarEntry) -> None:
        doc_id = earnings_calendar_doc_id(entry.ticker, entry.earnings_date, entry.quarter)
        self._collection.document(doc_id).set(entry.to_document(), merge=False)

    def list_all(self) -> list[EarningsCalendarEntry]:
        rows: list[EarningsCalendarEntry] = []
        for snapshot in self._collection.stream():
            rows.append(EarningsCalendarEntry.from_document(snapshot.to_dict() or {}))
        rows.sort(key=lambda row: (row.earnings_date, row.ticker))
        return rows

    def list_by_ticker(self, ticker: str) -> list[EarningsCalendarEntry]:
        normalized_ticker = normalize_ticker(ticker)
        rows: list[EarningsCalendarEntry] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            rows.append(EarningsCalendarEntry.from_document(data))
        rows.sort(key=lambda row: row.earnings_date)
        return rows

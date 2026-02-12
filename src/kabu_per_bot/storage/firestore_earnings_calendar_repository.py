from __future__ import annotations

import logging
from typing import Any

from kabu_per_bot.earnings import EarningsCalendarEntry
from kabu_per_bot.storage.firestore_schema import (
    COLLECTION_EARNINGS_CALENDAR,
    earnings_calendar_doc_id,
    normalize_ticker,
)


LOGGER = logging.getLogger(__name__)


class FirestoreEarningsCalendarRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_EARNINGS_CALENDAR)

    def upsert(self, entry: EarningsCalendarEntry) -> None:
        try:
            doc_id = earnings_calendar_doc_id(entry.ticker, entry.earnings_date, entry.quarter)
            self._collection.document(doc_id).set(entry.to_document(), merge=False)
        except Exception:
            LOGGER.exception(
                "earnings_calendar保存失敗: ticker=%s earnings_date=%s quarter=%s",
                entry.ticker,
                entry.earnings_date,
                entry.quarter,
            )
            raise

    def list_all(self) -> list[EarningsCalendarEntry]:
        rows: list[EarningsCalendarEntry] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            try:
                rows.append(EarningsCalendarEntry.from_document(data))
            except Exception as exc:
                LOGGER.error("earnings_calendar読込失敗: data=%s error=%s", data, exc)
        rows.sort(key=_row_sort_key)
        return rows

    def list_by_ticker(self, ticker: str) -> list[EarningsCalendarEntry]:
        normalized_ticker = normalize_ticker(ticker)
        rows: list[EarningsCalendarEntry] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            try:
                rows.append(EarningsCalendarEntry.from_document(data))
            except Exception as exc:
                LOGGER.error(
                    "earnings_calendar銘柄読込失敗: ticker=%s data=%s error=%s",
                    normalized_ticker,
                    data,
                    exc,
                )
        rows.sort(key=_row_sort_key)
        return rows


def _row_sort_key(row: EarningsCalendarEntry) -> tuple[str, str, str]:
    return (row.earnings_date, row.ticker, row.quarter or "NA")

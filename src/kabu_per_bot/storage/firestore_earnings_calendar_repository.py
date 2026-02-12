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

    def replace_by_ticker(self, ticker: str, entries: list[EarningsCalendarEntry]) -> None:
        normalized_ticker = normalize_ticker(ticker)
        expected_doc_ids: set[str] = set()
        for entry in entries:
            if normalize_ticker(entry.ticker) != normalized_ticker:
                raise ValueError(f"ticker mismatch: {entry.ticker} != {normalized_ticker}")
            expected_doc_ids.add(earnings_calendar_doc_id(entry.ticker, entry.earnings_date, entry.quarter))

        stale_doc_ids: list[str] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            try:
                existing = EarningsCalendarEntry.from_document(data)
            except Exception as exc:
                LOGGER.error(
                    "earnings_calendar既存読込失敗: ticker=%s data=%s error=%s",
                    normalized_ticker,
                    data,
                    exc,
                )
                continue
            doc_id = earnings_calendar_doc_id(existing.ticker, existing.earnings_date, existing.quarter)
            if doc_id not in expected_doc_ids:
                stale_doc_ids.append(doc_id)

        for doc_id in stale_doc_ids:
            try:
                self._collection.document(doc_id).delete()
            except Exception:
                LOGGER.exception("earnings_calendar削除失敗: ticker=%s doc_id=%s", normalized_ticker, doc_id)
                raise

        for entry in entries:
            self.upsert(entry)

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

from __future__ import annotations

from typing import Any

from kabu_per_bot.storage.firestore_schema import (
    COLLECTION_PRICE_BARS_DAILY,
    normalize_ticker,
    price_bars_daily_doc_id,
)
from kabu_per_bot.technical import PriceBarDaily


class FirestorePriceBarsDailyRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_PRICE_BARS_DAILY)

    def upsert(self, bar: PriceBarDaily) -> None:
        doc_id = price_bars_daily_doc_id(bar.ticker, bar.trade_date)
        self._collection.document(doc_id).set(bar.to_document(), merge=False)

    def get(self, ticker: str, trade_date: str) -> PriceBarDaily | None:
        doc_id = price_bars_daily_doc_id(ticker, trade_date)
        snapshot = self._collection.document(doc_id).get()
        if not snapshot.exists:
            return None
        return PriceBarDaily.from_document(snapshot.to_dict() or {})

    def list_recent(self, ticker: str, *, limit: int) -> list[PriceBarDaily]:
        normalized_ticker = normalize_ticker(ticker)
        rows: list[PriceBarDaily] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            rows.append(PriceBarDaily.from_document(data))
        rows.sort(key=lambda row: row.trade_date, reverse=True)
        return rows[:limit]

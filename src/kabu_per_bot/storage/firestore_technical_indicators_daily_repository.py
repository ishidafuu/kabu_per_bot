from __future__ import annotations

from typing import Any

from kabu_per_bot.storage.firestore_schema import (
    COLLECTION_TECHNICAL_INDICATORS_DAILY,
    normalize_ticker,
    technical_indicators_daily_doc_id,
)
from kabu_per_bot.technical import TechnicalIndicatorsDaily


class FirestoreTechnicalIndicatorsDailyRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_TECHNICAL_INDICATORS_DAILY)

    def upsert(self, indicators: TechnicalIndicatorsDaily) -> None:
        doc_id = technical_indicators_daily_doc_id(indicators.ticker, indicators.trade_date)
        self._collection.document(doc_id).set(indicators.to_document(), merge=False)

    def get(self, ticker: str, trade_date: str) -> TechnicalIndicatorsDaily | None:
        doc_id = technical_indicators_daily_doc_id(ticker, trade_date)
        snapshot = self._collection.document(doc_id).get()
        if not snapshot.exists:
            return None
        return TechnicalIndicatorsDaily.from_document(snapshot.to_dict() or {})

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalIndicatorsDaily]:
        normalized_ticker = normalize_ticker(ticker)
        rows: list[TechnicalIndicatorsDaily] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            rows.append(TechnicalIndicatorsDaily.from_document(data))
        rows.sort(key=lambda row: row.trade_date, reverse=True)
        return rows[:limit]

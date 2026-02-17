from __future__ import annotations

from typing import Any

from kabu_per_bot.metrics import MetricMedians
from kabu_per_bot.storage.firestore_schema import COLLECTION_METRIC_MEDIANS, metric_medians_doc_id, normalize_ticker


class FirestoreMetricMediansRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_METRIC_MEDIANS)

    def upsert(self, medians: MetricMedians) -> None:
        doc_id = metric_medians_doc_id(medians.ticker, medians.trade_date)
        self._collection.document(doc_id).set(medians.to_document(), merge=False)

    def get(self, ticker: str, trade_date: str) -> MetricMedians | None:
        doc_id = metric_medians_doc_id(ticker, trade_date)
        snapshot = self._collection.document(doc_id).get()
        if not snapshot.exists:
            return None
        return MetricMedians.from_document(snapshot.to_dict() or {})

    def list_recent(self, ticker: str, *, limit: int) -> list[MetricMedians]:
        normalized_ticker = normalize_ticker(ticker)
        rows: list[MetricMedians] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            rows.append(MetricMedians.from_document(data))
        rows.sort(key=lambda row: row.trade_date, reverse=True)
        return rows[:limit]

    def list_latest_by_tickers(self, tickers: list[str]) -> dict[str, MetricMedians]:
        normalized_tickers = {normalize_ticker(ticker) for ticker in tickers}
        if not normalized_tickers:
            return {}
        latest_by_ticker: dict[str, MetricMedians] = {}
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            ticker = str(data.get("ticker", "")).upper()
            if ticker not in normalized_tickers:
                continue
            row = MetricMedians.from_document(data)
            existing = latest_by_ticker.get(row.ticker)
            if existing is None or row.trade_date > existing.trade_date:
                latest_by_ticker[row.ticker] = row
        return latest_by_ticker

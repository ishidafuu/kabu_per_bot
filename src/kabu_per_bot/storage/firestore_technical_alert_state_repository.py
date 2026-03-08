from __future__ import annotations

from typing import Any

from kabu_per_bot.storage.firestore_schema import (
    COLLECTION_TECHNICAL_ALERT_STATE,
    normalize_ticker,
    technical_alert_state_doc_id,
)
from kabu_per_bot.technical import TechnicalAlertState


class FirestoreTechnicalAlertStateRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_TECHNICAL_ALERT_STATE)

    def upsert(self, state: TechnicalAlertState) -> None:
        doc_id = technical_alert_state_doc_id(state.ticker, state.rule_id)
        self._collection.document(doc_id).set(state.to_document(), merge=False)

    def get(self, ticker: str, rule_id: str) -> TechnicalAlertState | None:
        doc_id = technical_alert_state_doc_id(ticker, rule_id)
        snapshot = self._collection.document(doc_id).get()
        if not snapshot.exists:
            return None
        return TechnicalAlertState.from_document(snapshot.to_dict() or {})

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalAlertState]:
        normalized_ticker = normalize_ticker(ticker)
        rows: list[TechnicalAlertState] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            rows.append(TechnicalAlertState.from_document(data))
        rows.sort(key=lambda row: row.updated_at or "", reverse=True)
        return rows[:limit]

from __future__ import annotations

from typing import Any

from kabu_per_bot.signal import SignalState
from kabu_per_bot.storage.firestore_schema import COLLECTION_SIGNAL_STATE, normalize_ticker, signal_state_doc_id


class FirestoreSignalStateRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_SIGNAL_STATE)

    def upsert(self, state: SignalState) -> None:
        doc_id = signal_state_doc_id(state.ticker, state.trade_date)
        self._collection.document(doc_id).set(state.to_document(), merge=False)

    def get(self, ticker: str, trade_date: str) -> SignalState | None:
        doc_id = signal_state_doc_id(ticker, trade_date)
        snapshot = self._collection.document(doc_id).get()
        if not snapshot.exists:
            return None
        return SignalState.from_document(snapshot.to_dict() or {})

    def get_latest(self, ticker: str) -> SignalState | None:
        normalized_ticker = normalize_ticker(ticker)
        states: list[SignalState] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            if str(data.get("ticker", "")).upper() != normalized_ticker:
                continue
            states.append(SignalState.from_document(data))
        if not states:
            return None
        states.sort(key=lambda state: state.trade_date, reverse=True)
        return states[0]

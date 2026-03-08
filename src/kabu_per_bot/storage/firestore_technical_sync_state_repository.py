from __future__ import annotations

from typing import Any

from kabu_per_bot.storage.firestore_schema import (
    COLLECTION_TECHNICAL_SYNC_STATE,
    technical_sync_state_doc_id,
)
from kabu_per_bot.technical import TechnicalSyncState


class FirestoreTechnicalSyncStateRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_TECHNICAL_SYNC_STATE)

    def upsert(self, state: TechnicalSyncState) -> None:
        doc_id = technical_sync_state_doc_id(state.ticker)
        self._collection.document(doc_id).set(state.to_document(), merge=False)

    def get(self, ticker: str) -> TechnicalSyncState | None:
        doc_id = technical_sync_state_doc_id(ticker)
        snapshot = self._collection.document(doc_id).get()
        if not snapshot.exists:
            return None
        return TechnicalSyncState.from_document(snapshot.to_dict() or {})

    def list_recent(self, *, limit: int) -> list[TechnicalSyncState]:
        rows: list[TechnicalSyncState] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            rows.append(TechnicalSyncState.from_document(data))
        rows.sort(key=lambda row: row.last_run_at, reverse=True)
        return rows[:limit]

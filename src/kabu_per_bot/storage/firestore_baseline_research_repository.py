from __future__ import annotations

from typing import Any

from kabu_per_bot.baseline_research import BaselineResearchRecord
from kabu_per_bot.storage.firestore_schema import COLLECTION_BASELINE_RESEARCH, normalize_ticker


class FirestoreBaselineResearchRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_BASELINE_RESEARCH)

    def upsert(self, record: BaselineResearchRecord) -> None:
        self._collection.document(record.ticker).set(record.to_document(), merge=False)

    def get_latest(self, ticker: str) -> BaselineResearchRecord | None:
        normalized_ticker = normalize_ticker(ticker)
        snapshot = self._collection.document(normalized_ticker).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        return BaselineResearchRecord.from_document(data)

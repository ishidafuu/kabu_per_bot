from __future__ import annotations

from typing import Any

from kabu_per_bot.storage.firestore_schema import COLLECTION_TECHNICAL_PROFILES, technical_profile_doc_id
from kabu_per_bot.technical_profiles import TechnicalProfile


class FirestoreTechnicalProfilesRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_TECHNICAL_PROFILES)

    def get(self, profile_id: str) -> TechnicalProfile | None:
        doc_id = technical_profile_doc_id(profile_id)
        snapshot = self._collection.document(doc_id).get()
        if not snapshot.exists:
            return None
        return TechnicalProfile.from_document(snapshot.to_dict() or {})

    def list_all(self, *, include_inactive: bool = True) -> list[TechnicalProfile]:
        rows: list[TechnicalProfile] = []
        for snapshot in self._collection.stream():
            data = snapshot.to_dict() or {}
            row = TechnicalProfile.from_document(data)
            if not include_inactive and not row.is_active:
                continue
            rows.append(row)
        rows.sort(
            key=lambda row: (
                0 if row.profile_type.value == "SYSTEM" else 1,
                row.priority_order if row.priority_order is not None else 9999,
                row.name,
            )
        )
        return rows

    def upsert(self, profile: TechnicalProfile) -> None:
        self._collection.document(profile.profile_id).set(profile.to_document(), merge=False)

    def delete(self, profile_id: str) -> bool:
        doc_id = technical_profile_doc_id(profile_id)
        ref = self._collection.document(doc_id)
        snapshot = ref.get()
        if not snapshot.exists:
            return False
        ref.delete()
        return True

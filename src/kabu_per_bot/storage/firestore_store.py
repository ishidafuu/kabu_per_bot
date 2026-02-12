from __future__ import annotations

from typing import Any, Mapping


class FirestoreDocumentStore:
    """Firestore adapter used by migration scripts."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _document_ref(self, path: str) -> Any:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 0 or len(parts) % 2 != 0:
            raise ValueError(f"Document path must have even segments: {path}")

        ref: Any = self._client
        for index in range(0, len(parts), 2):
            collection_name = parts[index]
            document_id = parts[index + 1]
            ref = ref.collection(collection_name).document(document_id)
        return ref

    def get_document(self, path: str) -> Mapping[str, Any] | None:
        ref = self._document_ref(path)
        snapshot = ref.get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict()
        return data if data is not None else {}

    def set_document(self, path: str, data: Mapping[str, Any], *, merge: bool = False) -> None:
        ref = self._document_ref(path)
        ref.set(dict(data), merge=merge)


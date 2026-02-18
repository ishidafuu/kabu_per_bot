from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kabu_per_bot.runtime_settings import GlobalRuntimeSettings
from kabu_per_bot.storage.firestore_schema import COLLECTION_GLOBAL_SETTINGS


GLOBAL_SETTINGS_DOC_ID = "runtime"


class FirestoreGlobalSettingsRepository:
    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION_GLOBAL_SETTINGS)

    def get_global_settings(self) -> GlobalRuntimeSettings:
        snapshot = self._collection.document(GLOBAL_SETTINGS_DOC_ID).get()
        if not snapshot.exists:
            return GlobalRuntimeSettings()
        data = snapshot.to_dict() or {}
        cooldown_hours = _read_optional_positive_int(data.get("cooldown_hours"), key="cooldown_hours")
        updated_at = _read_optional_datetime_iso(data.get("updated_at"))
        updated_by = _read_optional_string(data.get("updated_by"))
        return GlobalRuntimeSettings(
            cooldown_hours=cooldown_hours,
            updated_at=updated_at,
            updated_by=updated_by,
        )

    def upsert_global_settings(
        self,
        *,
        cooldown_hours: int,
        updated_at: str,
        updated_by: str | None,
    ) -> None:
        if cooldown_hours <= 0:
            raise ValueError("cooldown_hours must be > 0")
        row = {
            "cooldown_hours": int(cooldown_hours),
            "updated_at": _read_required_datetime_iso(updated_at),
            "updated_by": _read_optional_string(updated_by),
        }
        self._collection.document(GLOBAL_SETTINGS_DOC_ID).set(row, merge=True)


def _read_optional_positive_int(value: Any, *, key: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be integer: {value}") from exc
    if parsed <= 0:
        raise ValueError(f"{key} must be > 0: {parsed}")
    return parsed


def _read_optional_datetime_iso(value: Any) -> str | None:
    if value is None:
        return None
    return _read_required_datetime_iso(value)


def _read_required_datetime_iso(value: Any) -> str:
    if value is None:
        raise ValueError("updated_at is required")
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _read_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized

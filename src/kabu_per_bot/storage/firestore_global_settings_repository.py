from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from kabu_per_bot.immediate_schedule import ImmediateSchedule, JST_TIMEZONE, validate_immediate_schedule
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
        immediate_schedule = _read_optional_immediate_schedule(data)
        updated_at = _read_optional_datetime_iso(data.get("updated_at"))
        updated_by = _read_optional_string(data.get("updated_by"))
        return GlobalRuntimeSettings(
            cooldown_hours=cooldown_hours,
            immediate_schedule=immediate_schedule,
            updated_at=updated_at,
            updated_by=updated_by,
        )

    def upsert_global_settings(
        self,
        *,
        cooldown_hours: int | None = None,
        immediate_schedule: ImmediateSchedule | None = None,
        updated_at: str,
        updated_by: str | None,
    ) -> None:
        if cooldown_hours is None and immediate_schedule is None:
            raise ValueError("at least one setting update is required")
        row = {
            "updated_at": _read_required_datetime_iso(updated_at),
            "updated_by": _read_optional_string(updated_by),
        }
        if cooldown_hours is not None:
            if cooldown_hours <= 0:
                raise ValueError("cooldown_hours must be > 0")
            row["cooldown_hours"] = int(cooldown_hours)
        if immediate_schedule is not None:
            validate_immediate_schedule(immediate_schedule)
            row.update(
                {
                    "immediate_schedule_enabled": bool(immediate_schedule.enabled),
                    "immediate_schedule_timezone": immediate_schedule.timezone,
                    "immediate_open_window_start": immediate_schedule.open_window_start,
                    "immediate_open_window_end": immediate_schedule.open_window_end,
                    "immediate_open_window_interval_min": int(immediate_schedule.open_window_interval_min),
                    "immediate_close_window_start": immediate_schedule.close_window_start,
                    "immediate_close_window_end": immediate_schedule.close_window_end,
                    "immediate_close_window_interval_min": int(immediate_schedule.close_window_interval_min),
                }
            )
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


def _read_optional_bool(value: Any, *, key: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"{key} must be boolean: {value}")


def _read_optional_hhmm(value: Any, *, key: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) != 5:
        raise ValueError(f"{key} must match HH:MM format: {value}")
    return normalized


def _read_optional_immediate_schedule(data: dict[str, Any]) -> ImmediateSchedule | None:
    keys = (
        "immediate_schedule_enabled",
        "immediate_schedule_timezone",
        "immediate_open_window_start",
        "immediate_open_window_end",
        "immediate_open_window_interval_min",
        "immediate_close_window_start",
        "immediate_close_window_end",
        "immediate_close_window_interval_min",
    )
    if not any(key in data for key in keys):
        return None

    default = ImmediateSchedule.default()
    enabled_value = _read_optional_bool(data.get("immediate_schedule_enabled"), key="immediate_schedule_enabled")
    timezone_value = _read_optional_string(data.get("immediate_schedule_timezone"))
    open_start_value = _read_optional_hhmm(data.get("immediate_open_window_start"), key="immediate_open_window_start")
    open_end_value = _read_optional_hhmm(data.get("immediate_open_window_end"), key="immediate_open_window_end")
    open_interval_value = _read_optional_positive_int(
        data.get("immediate_open_window_interval_min"),
        key="immediate_open_window_interval_min",
    )
    close_start_value = _read_optional_hhmm(
        data.get("immediate_close_window_start"),
        key="immediate_close_window_start",
    )
    close_end_value = _read_optional_hhmm(
        data.get("immediate_close_window_end"),
        key="immediate_close_window_end",
    )
    close_interval_value = _read_optional_positive_int(
        data.get("immediate_close_window_interval_min"),
        key="immediate_close_window_interval_min",
    )

    schedule = ImmediateSchedule(
        enabled=enabled_value if enabled_value is not None else default.enabled,
        timezone=timezone_value or JST_TIMEZONE,
        open_window_start=open_start_value or default.open_window_start,
        open_window_end=open_end_value or default.open_window_end,
        open_window_interval_min=open_interval_value or default.open_window_interval_min,
        close_window_start=close_start_value or default.close_window_start,
        close_window_end=close_end_value or default.close_window_end,
        close_window_interval_min=close_interval_value or default.close_window_interval_min,
    )
    validate_immediate_schedule(schedule)
    return schedule

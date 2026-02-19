from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal
from zoneinfo import ZoneInfo


JST_TIMEZONE = "Asia/Tokyo"
_HHMM_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_MIN_INTERVAL = 1
_MAX_INTERVAL = 60

WindowKind = Literal["open", "close"]


@dataclass(frozen=True)
class ImmediateSchedule:
    enabled: bool
    timezone: str
    open_window_start: str
    open_window_end: str
    open_window_interval_min: int
    close_window_start: str
    close_window_end: str
    close_window_interval_min: int

    @classmethod
    def default(cls) -> "ImmediateSchedule":
        return cls(
            enabled=True,
            timezone=JST_TIMEZONE,
            open_window_start="09:00",
            open_window_end="10:00",
            open_window_interval_min=15,
            close_window_start="14:30",
            close_window_end="15:30",
            close_window_interval_min=10,
        )


@dataclass(frozen=True)
class ImmediateWindowDecision:
    should_run: bool
    reason: str


def validate_immediate_schedule(schedule: ImmediateSchedule) -> None:
    if schedule.timezone != JST_TIMEZONE:
        raise ValueError(f"timezone must be fixed to {JST_TIMEZONE}.")

    _require_hhmm(schedule.open_window_start, key="open_window_start")
    _require_hhmm(schedule.open_window_end, key="open_window_end")
    _require_hhmm(schedule.close_window_start, key="close_window_start")
    _require_hhmm(schedule.close_window_end, key="close_window_end")

    _require_interval(schedule.open_window_interval_min, key="open_window_interval_min")
    _require_interval(schedule.close_window_interval_min, key="close_window_interval_min")

    open_start = _to_minutes(schedule.open_window_start)
    open_end = _to_minutes(schedule.open_window_end)
    close_start = _to_minutes(schedule.close_window_start)
    close_end = _to_minutes(schedule.close_window_end)

    if open_start >= open_end:
        raise ValueError("open_window_start must be earlier than open_window_end.")
    if close_start >= close_end:
        raise ValueError("close_window_start must be earlier than close_window_end.")

    if _is_overlapped(start_a=open_start, end_a=open_end, start_b=close_start, end_b=close_end):
        raise ValueError("open/close windows must not overlap.")


def evaluate_window_schedule(
    *,
    schedule: ImmediateSchedule,
    window_kind: WindowKind,
    now_iso: str | None = None,
) -> ImmediateWindowDecision:
    validate_immediate_schedule(schedule)
    if not schedule.enabled:
        return ImmediateWindowDecision(should_run=False, reason="immediate_schedule is disabled")

    now_jst = _resolve_now_jst(now_iso=now_iso, timezone_name=schedule.timezone)
    now_minutes = now_jst.hour * 60 + now_jst.minute

    if window_kind == "open":
        start_text = schedule.open_window_start
        end_text = schedule.open_window_end
        interval = schedule.open_window_interval_min
    else:
        start_text = schedule.close_window_start
        end_text = schedule.close_window_end
        interval = schedule.close_window_interval_min

    start = _to_minutes(start_text)
    end = _to_minutes(end_text)
    if not (start <= now_minutes < end):
        return ImmediateWindowDecision(should_run=False, reason="outside configured window")

    if ((now_minutes - start) % interval) != 0:
        return ImmediateWindowDecision(should_run=False, reason="interval gate")
    return ImmediateWindowDecision(should_run=True, reason="window and interval matched")


def _require_hhmm(value: str, *, key: str) -> None:
    text = value.strip()
    if not _HHMM_PATTERN.fullmatch(text):
        raise ValueError(f"{key} must match HH:MM format.")


def _require_interval(value: int, *, key: str) -> None:
    if not (_MIN_INTERVAL <= value <= _MAX_INTERVAL):
        raise ValueError(f"{key} must be between {_MIN_INTERVAL} and {_MAX_INTERVAL}.")


def _to_minutes(value: str) -> int:
    hour_text, minute_text = value.split(":", 1)
    return int(hour_text) * 60 + int(minute_text)


def _is_overlapped(*, start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return max(start_a, start_b) < min(end_a, end_b)


def _resolve_now_jst(*, now_iso: str | None, timezone_name: str) -> datetime:
    if timezone_name != JST_TIMEZONE:
        raise ValueError(f"timezone_name must be fixed to {JST_TIMEZONE}.")
    if now_iso is None:
        now = datetime.now(ZoneInfo("UTC"))
    else:
        now = datetime.fromisoformat(now_iso)
        if now.tzinfo is None:
            raise ValueError("now_iso must include timezone offset, e.g. '+09:00'.")
    return now.astimezone(ZoneInfo(timezone_name))

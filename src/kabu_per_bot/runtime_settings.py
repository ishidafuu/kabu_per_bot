from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kabu_per_bot.immediate_schedule import ImmediateSchedule


@dataclass(frozen=True)
class GlobalRuntimeSettings:
    cooldown_hours: int | None = None
    immediate_schedule: ImmediateSchedule | None = None
    updated_at: str | None = None
    updated_by: str | None = None


@dataclass(frozen=True)
class RuntimeSettings:
    cooldown_hours: int
    immediate_schedule: ImmediateSchedule
    source: str
    updated_at: str | None = None
    updated_by: str | None = None


class GlobalSettingsReader(Protocol):
    def get_global_settings(self) -> GlobalRuntimeSettings:
        """Get global runtime settings."""


def resolve_runtime_settings(
    *,
    default_cooldown_hours: int,
    default_immediate_schedule: ImmediateSchedule | None = None,
    global_settings: GlobalRuntimeSettings,
) -> RuntimeSettings:
    cooldown_hours = (
        global_settings.cooldown_hours if global_settings.cooldown_hours is not None else default_cooldown_hours
    )
    immediate_schedule = global_settings.immediate_schedule or default_immediate_schedule or ImmediateSchedule.default()
    source = (
        "firestore"
        if global_settings.cooldown_hours is not None or global_settings.immediate_schedule is not None
        else "env_default"
    )
    return RuntimeSettings(
        cooldown_hours=cooldown_hours,
        immediate_schedule=immediate_schedule,
        source=source,
        updated_at=global_settings.updated_at,
        updated_by=global_settings.updated_by,
    )

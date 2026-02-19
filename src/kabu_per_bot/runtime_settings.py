from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kabu_per_bot.grok_sns_settings import GrokSnsSettings
from kabu_per_bot.immediate_schedule import ImmediateSchedule


@dataclass(frozen=True)
class GlobalRuntimeSettings:
    cooldown_hours: int | None = None
    intel_notification_max_age_days: int | None = None
    immediate_schedule: ImmediateSchedule | None = None
    grok_sns_settings: GrokSnsSettings | None = None
    updated_at: str | None = None
    updated_by: str | None = None


@dataclass(frozen=True)
class RuntimeSettings:
    cooldown_hours: int
    immediate_schedule: ImmediateSchedule
    source: str
    grok_sns_settings: GrokSnsSettings
    intel_notification_max_age_days: int = 30
    updated_at: str | None = None
    updated_by: str | None = None


class GlobalSettingsReader(Protocol):
    def get_global_settings(self) -> GlobalRuntimeSettings:
        """Get global runtime settings."""


def resolve_runtime_settings(
    *,
    default_cooldown_hours: int,
    default_intel_notification_max_age_days: int = 30,
    default_immediate_schedule: ImmediateSchedule | None = None,
    default_grok_sns_settings: GrokSnsSettings | None = None,
    global_settings: GlobalRuntimeSettings,
) -> RuntimeSettings:
    cooldown_hours = (
        global_settings.cooldown_hours if global_settings.cooldown_hours is not None else default_cooldown_hours
    )
    intel_notification_max_age_days = (
        global_settings.intel_notification_max_age_days
        if global_settings.intel_notification_max_age_days is not None
        else default_intel_notification_max_age_days
    )
    immediate_schedule = global_settings.immediate_schedule or default_immediate_schedule or ImmediateSchedule.default()
    grok_sns_settings = global_settings.grok_sns_settings or default_grok_sns_settings or GrokSnsSettings.default()
    source = (
        "firestore"
        if (
            global_settings.cooldown_hours is not None
            or global_settings.intel_notification_max_age_days is not None
            or global_settings.immediate_schedule is not None
            or global_settings.grok_sns_settings is not None
        )
        else "env_default"
    )
    return RuntimeSettings(
        cooldown_hours=cooldown_hours,
        intel_notification_max_age_days=intel_notification_max_age_days,
        immediate_schedule=immediate_schedule,
        grok_sns_settings=grok_sns_settings,
        source=source,
        updated_at=global_settings.updated_at,
        updated_by=global_settings.updated_by,
    )

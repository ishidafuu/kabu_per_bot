from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GlobalRuntimeSettings:
    cooldown_hours: int | None = None
    updated_at: str | None = None
    updated_by: str | None = None


@dataclass(frozen=True)
class RuntimeSettings:
    cooldown_hours: int
    source: str
    updated_at: str | None = None
    updated_by: str | None = None


class GlobalSettingsReader(Protocol):
    def get_global_settings(self) -> GlobalRuntimeSettings:
        """Get global runtime settings."""


def resolve_runtime_settings(
    *,
    default_cooldown_hours: int,
    global_settings: GlobalRuntimeSettings,
) -> RuntimeSettings:
    cooldown_hours = global_settings.cooldown_hours
    if cooldown_hours is None:
        return RuntimeSettings(
            cooldown_hours=default_cooldown_hours,
            source="env_default",
            updated_at=global_settings.updated_at,
            updated_by=global_settings.updated_by,
        )
    return RuntimeSettings(
        cooldown_hours=cooldown_hours,
        source="firestore",
        updated_at=global_settings.updated_at,
        updated_by=global_settings.updated_by,
    )

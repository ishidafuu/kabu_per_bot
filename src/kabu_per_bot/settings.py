from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Mapping
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kabu_per_bot.grok_sns_settings import (
    GrokSnsSettings,
    default_grok_prompt_template,
    validate_grok_sns_settings,
)


DEFAULT_TIMEZONE = "Asia/Tokyo"
DEFAULT_WINDOW_1W_DAYS = 5
DEFAULT_WINDOW_3M_DAYS = 63
DEFAULT_WINDOW_1Y_DAYS = 252
DEFAULT_COOLDOWN_HOURS = 2
DEFAULT_INTEL_NOTIFICATION_MAX_AGE_DAYS = 30
_HHMM_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class SettingsError(ValueError):
    """Raised when settings values are invalid."""


@dataclass(frozen=True)
class AppSettings:
    app_env: str
    timezone: str
    window_1w_days: int
    window_3m_days: int
    window_1y_days: int
    cooldown_hours: int
    firestore_project_id: str
    ai_notifications_enabled: bool
    x_api_bearer_token: str
    grok_api_key: str = ""
    grok_api_base_url: str = "https://api.x.ai/v1"
    grok_management_api_key: str = ""
    grok_management_team_id: str = ""
    grok_management_api_base_url: str = "https://management-api.x.ai"
    grok_model_fast: str = "grok-4-1-fast-non-reasoning"
    grok_model_reasoning: str = "grok-4-1-fast-reasoning"
    vertex_ai_location: str = "global"
    vertex_ai_model: str = "gemini-2.0-flash-001"
    grok_sns_enabled: bool = False
    grok_sns_scheduled_time: str = "21:10"
    grok_sns_per_ticker_cooldown_hours: int = 24
    grok_sns_prompt_template: str = field(default_factory=default_grok_prompt_template)
    intel_notification_max_age_days: int = DEFAULT_INTEL_NOTIFICATION_MAX_AGE_DAYS


def _read_dotenv(dotenv_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not dotenv_path.exists():
        return values

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def _get_str(values: Mapping[str, str], key: str, default: str) -> str:
    value = values.get(key, default).strip()
    if not value:
        raise SettingsError(f"{key} must not be empty.")
    return value


def _get_int(values: Mapping[str, str], key: str, default: int) -> int:
    raw_value = values.get(key)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise SettingsError(f"{key} must be integer: {raw_value}") from exc
    if value <= 0:
        raise SettingsError(f"{key} must be > 0: {value}")
    return value


def _get_bool(values: Mapping[str, str], key: str, default: bool) -> bool:
    raw_value = values.get(key)
    if raw_value is None or raw_value.strip() == "":
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SettingsError(f"{key} must be boolean: {raw_value}")


def _get_hhmm(values: Mapping[str, str], key: str, default: str) -> str:
    value = values.get(key, default).strip()
    if not _HHMM_PATTERN.fullmatch(value):
        raise SettingsError(f"{key} must match HH:MM format: {value}")
    return value


def load_settings(
    *,
    env: Mapping[str, str] | None = None,
    dotenv_path: str | Path = ".env",
) -> AppSettings:
    """Load settings from .env and environment variables.

    Priority: OS environment > .env > default.
    """

    env_values = dict(env) if env is not None else dict(os.environ)
    dotenv_values = _read_dotenv(Path(dotenv_path))
    merged: dict[str, str] = {**dotenv_values, **env_values}

    timezone = _get_str(merged, "APP_TIMEZONE", DEFAULT_TIMEZONE)
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise SettingsError(f"APP_TIMEZONE is invalid: {timezone}") from exc

    window_1w_days = _get_int(merged, "WINDOW_1W_DAYS", DEFAULT_WINDOW_1W_DAYS)
    window_3m_days = _get_int(merged, "WINDOW_3M_DAYS", DEFAULT_WINDOW_3M_DAYS)
    window_1y_days = _get_int(merged, "WINDOW_1Y_DAYS", DEFAULT_WINDOW_1Y_DAYS)
    if not (window_1w_days <= window_3m_days <= window_1y_days):
        raise SettingsError("WINDOW_* must satisfy 1W <= 3M <= 1Y.")

    prompt_template = merged.get("GROK_SNS_PROMPT_TEMPLATE", "").strip() or default_grok_prompt_template()
    grok_sns_settings = GrokSnsSettings(
        enabled=_get_bool(merged, "GROK_SNS_ENABLED", False),
        scheduled_time=_get_hhmm(merged, "GROK_SNS_SCHEDULED_TIME", "21:10"),
        per_ticker_cooldown_hours=_get_int(merged, "GROK_SNS_PER_TICKER_COOLDOWN_HOURS", 24),
        prompt_template=prompt_template,
    )
    try:
        validate_grok_sns_settings(grok_sns_settings)
    except ValueError as exc:
        raise SettingsError(str(exc)) from exc

    return AppSettings(
        app_env=_get_str(merged, "APP_ENV", "development"),
        timezone=timezone,
        window_1w_days=window_1w_days,
        window_3m_days=window_3m_days,
        window_1y_days=window_1y_days,
        cooldown_hours=_get_int(merged, "COOLDOWN_HOURS", DEFAULT_COOLDOWN_HOURS),
        firestore_project_id=merged.get("FIRESTORE_PROJECT_ID", "").strip(),
        ai_notifications_enabled=_get_bool(merged, "AI_NOTIFICATIONS_ENABLED", False),
        x_api_bearer_token=merged.get("X_API_BEARER_TOKEN", "").strip(),
        grok_api_key=merged.get("GROK_API_KEY", "").strip(),
        grok_api_base_url=_get_str(merged, "GROK_API_BASE_URL", "https://api.x.ai/v1"),
        grok_management_api_key=merged.get("GROK_MANAGEMENT_API_KEY", "").strip(),
        grok_management_team_id=merged.get("GROK_MANAGEMENT_TEAM_ID", "").strip(),
        grok_management_api_base_url=_get_str(merged, "GROK_MANAGEMENT_API_BASE_URL", "https://management-api.x.ai"),
        grok_model_fast=_get_str(merged, "GROK_MODEL_FAST", "grok-4-1-fast-non-reasoning"),
        grok_model_reasoning=_get_str(merged, "GROK_MODEL_REASONING", "grok-4-1-fast-reasoning"),
        vertex_ai_location=_get_str(merged, "VERTEX_AI_LOCATION", "global"),
        vertex_ai_model=_get_str(merged, "VERTEX_AI_MODEL", "gemini-2.0-flash-001"),
        grok_sns_enabled=grok_sns_settings.enabled,
        grok_sns_scheduled_time=grok_sns_settings.scheduled_time,
        grok_sns_per_ticker_cooldown_hours=grok_sns_settings.per_ticker_cooldown_hours,
        grok_sns_prompt_template=grok_sns_settings.prompt_template,
        intel_notification_max_age_days=_get_int(
            merged,
            "INTEL_NOTIFICATION_MAX_AGE_DAYS",
            DEFAULT_INTEL_NOTIFICATION_MAX_AGE_DAYS,
        ),
    )

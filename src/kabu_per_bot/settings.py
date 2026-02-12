from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import os


DEFAULT_TIMEZONE = "Asia/Tokyo"
DEFAULT_WINDOW_1W_DAYS = 5
DEFAULT_WINDOW_3M_DAYS = 63
DEFAULT_WINDOW_1Y_DAYS = 252
DEFAULT_COOLDOWN_HOURS = 2


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

    return AppSettings(
        app_env=_get_str(merged, "APP_ENV", "development"),
        timezone=_get_str(merged, "APP_TIMEZONE", DEFAULT_TIMEZONE),
        window_1w_days=_get_int(merged, "WINDOW_1W_DAYS", DEFAULT_WINDOW_1W_DAYS),
        window_3m_days=_get_int(merged, "WINDOW_3M_DAYS", DEFAULT_WINDOW_3M_DAYS),
        window_1y_days=_get_int(merged, "WINDOW_1Y_DAYS", DEFAULT_WINDOW_1Y_DAYS),
        cooldown_hours=_get_int(merged, "COOLDOWN_HOURS", DEFAULT_COOLDOWN_HOURS),
    )


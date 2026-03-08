from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from kabu_per_bot.storage.firestore_schema import technical_profile_doc_id


SYSTEM_PROFILE_KEYS = (
    "low_liquidity",
    "large_core",
    "value_dividend",
    "small_growth",
)


class TechnicalProfileType(str, Enum):
    SYSTEM = "SYSTEM"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True)
class TechnicalProfile:
    profile_id: str
    profile_type: TechnicalProfileType
    profile_key: str
    name: str
    description: str
    base_profile_key: str | None = None
    priority_order: int | None = None
    manual_assign_recommended: bool = False
    auto_assign: dict[str, Any] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)
    weights: dict[str, int] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    strong_alerts: tuple[str, ...] = ()
    weak_alerts: tuple[str, ...] = ()
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        profile_id = technical_profile_doc_id(self.profile_id)
        profile_key = str(self.profile_key).strip()
        name = str(self.name).strip()
        description = str(self.description).strip()
        if not profile_key:
            raise ValueError("profile_key is required")
        if not name:
            raise ValueError("name is required")
        if not description:
            raise ValueError("description is required")
        object.__setattr__(self, "profile_id", profile_id)
        object.__setattr__(self, "profile_key", profile_key)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "base_profile_key", _as_str_or_none(self.base_profile_key))
        object.__setattr__(self, "priority_order", _as_int_or_none(self.priority_order))
        object.__setattr__(self, "manual_assign_recommended", bool(self.manual_assign_recommended))
        object.__setattr__(self, "auto_assign", _as_dict(self.auto_assign))
        object.__setattr__(self, "thresholds", _normalize_float_map(self.thresholds))
        object.__setattr__(self, "weights", _normalize_int_map(self.weights))
        object.__setattr__(self, "flags", _normalize_bool_map(self.flags))
        object.__setattr__(self, "strong_alerts", _normalize_string_tuple(self.strong_alerts))
        object.__setattr__(self, "weak_alerts", _normalize_string_tuple(self.weak_alerts))
        object.__setattr__(self, "is_active", bool(self.is_active))
        object.__setattr__(self, "created_at", _as_str_or_none(self.created_at))
        object.__setattr__(self, "updated_at", _as_str_or_none(self.updated_at))

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "TechnicalProfile":
        return cls(
            profile_id=str(data["profile_id"]),
            profile_type=TechnicalProfileType(str(data["profile_type"]).strip().upper()),
            profile_key=str(data["profile_key"]),
            name=str(data["name"]),
            description=str(data["description"]),
            base_profile_key=_as_str_or_none(data.get("base_profile_key")),
            priority_order=_as_int_or_none(data.get("priority_order")),
            manual_assign_recommended=bool(data.get("manual_assign_recommended", False)),
            auto_assign=_as_dict(data.get("auto_assign")),
            thresholds=_as_dict(data.get("thresholds")),
            weights=_as_dict(data.get("weights")),
            flags=_as_dict(data.get("flags")),
            strong_alerts=tuple(_as_string_list(data.get("strong_alerts"))),
            weak_alerts=tuple(_as_string_list(data.get("weak_alerts"))),
            is_active=bool(data.get("is_active", True)),
            created_at=_as_str_or_none(data.get("created_at")),
            updated_at=_as_str_or_none(data.get("updated_at")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_type": self.profile_type.value,
            "profile_key": self.profile_key,
            "name": self.name,
            "description": self.description,
            "base_profile_key": self.base_profile_key,
            "priority_order": self.priority_order,
            "manual_assign_recommended": self.manual_assign_recommended,
            "auto_assign": dict(self.auto_assign),
            "thresholds": dict(self.thresholds),
            "weights": dict(self.weights),
            "flags": dict(self.flags),
            "strong_alerts": list(self.strong_alerts),
            "weak_alerts": list(self.weak_alerts),
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TechnicalProfilesRepository(Protocol):
    def get(self, profile_id: str) -> TechnicalProfile | None:
        """Get profile by id."""

    def list_all(self, *, include_inactive: bool = True) -> list[TechnicalProfile]:
        """List profiles."""

    def upsert(self, profile: TechnicalProfile) -> None:
        """Persist profile."""

    def delete(self, profile_id: str) -> bool:
        """Delete profile."""


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return {str(key): item for key, item in value.items()}


def _normalize_float_map(value: dict[str, Any]) -> dict[str, float]:
    return {str(key): float(item) for key, item in _as_dict(value).items()}


def _normalize_int_map(value: dict[str, Any]) -> dict[str, int]:
    return {str(key): int(item) for key, item in _as_dict(value).items()}


def _normalize_bool_map(value: dict[str, Any]) -> dict[str, bool]:
    return {str(key): bool(item) for key, item in _as_dict(value).items()}


def _normalize_string_tuple(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(_as_string_list(values))


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected list")
    return [str(item).strip() for item in value if str(item).strip()]


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)

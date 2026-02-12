from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from kabu_per_bot.storage.firestore_schema import normalize_ticker


class WatchlistError(ValueError):
    """Base watchlist error."""


class WatchlistLimitExceededError(WatchlistError):
    """Raised when watchlist size exceeds the configured maximum."""


class WatchlistNotFoundError(WatchlistError):
    """Raised when a target ticker does not exist."""


class WatchlistAlreadyExistsError(WatchlistError):
    """Raised when creating an already-existing ticker."""


class MetricType(str, Enum):
    PER = "PER"
    PSR = "PSR"


class NotifyChannel(str, Enum):
    DISCORD = "DISCORD"
    LINE = "LINE"
    BOTH = "BOTH"
    OFF = "OFF"


class NotifyTiming(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    AT_21 = "AT_21"
    OFF = "OFF"


@dataclass(frozen=True)
class WatchlistItem:
    ticker: str
    name: str
    metric_type: MetricType
    notify_channel: NotifyChannel
    notify_timing: NotifyTiming
    ai_enabled: bool = False
    is_active: bool = True
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> WatchlistItem:
        return cls(
            ticker=normalize_ticker(str(data["ticker"])),
            name=str(data["name"]).strip(),
            metric_type=MetricType(str(data["metric_type"]).strip().upper()),
            notify_channel=NotifyChannel(str(data["notify_channel"]).strip().upper()),
            notify_timing=NotifyTiming(str(data["notify_timing"]).strip().upper()),
            ai_enabled=bool(data.get("ai_enabled", False)),
            is_active=bool(data.get("is_active", True)),
            created_at=(str(data["created_at"]) if data.get("created_at") else None),
            updated_at=(str(data["updated_at"]) if data.get("updated_at") else None),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "metric_type": self.metric_type.value,
            "notify_channel": self.notify_channel.value,
            "notify_timing": self.notify_timing.value,
            "ai_enabled": self.ai_enabled,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class WatchlistRepository(Protocol):
    def count(self) -> int:
        """Return current watchlist count."""

    def get(self, ticker: str) -> WatchlistItem | None:
        """Get item by ticker."""

    def list_all(self) -> list[WatchlistItem]:
        """List all watchlist items."""

    def create(self, item: WatchlistItem) -> None:
        """Create item."""

    def update(self, item: WatchlistItem) -> None:
        """Update item."""

    def delete(self, ticker: str) -> bool:
        """Delete item and return whether the item existed."""


class WatchlistService:
    def __init__(self, repository: WatchlistRepository, *, max_items: int = 100) -> None:
        if max_items <= 0:
            raise WatchlistError("max_items must be > 0.")
        self._repository = repository
        self._max_items = max_items

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_name(name: str) -> str:
        value = name.strip()
        if not value:
            raise WatchlistError("name must not be empty.")
        return value

    @staticmethod
    def _enum_input(value: Enum | str) -> str:
        if isinstance(value, Enum):
            return str(value.value).strip().upper()
        return str(value).strip().upper()

    def add_item(
        self,
        *,
        ticker: str,
        name: str,
        metric_type: MetricType | str,
        notify_channel: NotifyChannel | str,
        notify_timing: NotifyTiming | str,
        ai_enabled: bool = False,
        is_active: bool = True,
        now_iso: str | None = None,
    ) -> WatchlistItem:
        normalized_ticker = normalize_ticker(ticker)
        if self._repository.get(normalized_ticker) is not None:
            raise WatchlistAlreadyExistsError(f"{normalized_ticker} already exists.")
        if self._repository.count() >= self._max_items:
            raise WatchlistLimitExceededError(f"watchlist limit exceeded: max={self._max_items}")

        current_time = now_iso or self._now_iso()
        item = WatchlistItem(
            ticker=normalized_ticker,
            name=self._normalize_name(name),
            metric_type=MetricType(self._enum_input(metric_type)),
            notify_channel=NotifyChannel(self._enum_input(notify_channel)),
            notify_timing=NotifyTiming(self._enum_input(notify_timing)),
            ai_enabled=bool(ai_enabled),
            is_active=bool(is_active),
            created_at=current_time,
            updated_at=current_time,
        )
        self._repository.create(item)
        return item

    def list_items(self) -> list[WatchlistItem]:
        return self._repository.list_all()

    def get_item(self, ticker: str) -> WatchlistItem:
        normalized_ticker = normalize_ticker(ticker)
        existing = self._repository.get(normalized_ticker)
        if existing is None:
            raise WatchlistNotFoundError(f"{normalized_ticker} not found.")
        return existing

    def update_item(
        self,
        ticker: str,
        *,
        name: str | None = None,
        metric_type: MetricType | str | None = None,
        notify_channel: NotifyChannel | str | None = None,
        notify_timing: NotifyTiming | str | None = None,
        ai_enabled: bool | None = None,
        is_active: bool | None = None,
        now_iso: str | None = None,
    ) -> WatchlistItem:
        normalized_ticker = normalize_ticker(ticker)
        existing = self._repository.get(normalized_ticker)
        if existing is None:
            raise WatchlistNotFoundError(f"{normalized_ticker} not found.")

        updated = WatchlistItem(
            ticker=existing.ticker,
            name=self._normalize_name(name) if name is not None else existing.name,
            metric_type=(
                MetricType(self._enum_input(metric_type)) if metric_type is not None else existing.metric_type
            ),
            notify_channel=(
                NotifyChannel(self._enum_input(notify_channel))
                if notify_channel is not None
                else existing.notify_channel
            ),
            notify_timing=(
                NotifyTiming(self._enum_input(notify_timing))
                if notify_timing is not None
                else existing.notify_timing
            ),
            ai_enabled=existing.ai_enabled if ai_enabled is None else bool(ai_enabled),
            is_active=existing.is_active if is_active is None else bool(is_active),
            created_at=existing.created_at,
            updated_at=now_iso or self._now_iso(),
        )
        self._repository.update(updated)
        return updated

    def delete_item(self, ticker: str) -> None:
        normalized_ticker = normalize_ticker(ticker)
        deleted = self._repository.delete(normalized_ticker)
        if not deleted:
            raise WatchlistNotFoundError(f"{normalized_ticker} not found.")

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


class WatchlistPersistenceError(RuntimeError):
    """Raised when consistency could not be guaranteed in storage operations."""


class CreateResult(str, Enum):
    CREATED = "CREATED"
    DUPLICATE = "DUPLICATE"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"


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


class WatchlistHistoryAction(str, Enum):
    ADD = "ADD"
    REMOVE = "REMOVE"


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
            ai_enabled=_coerce_bool(data.get("ai_enabled"), field_name="ai_enabled", default=False),
            is_active=_coerce_bool(data.get("is_active"), field_name="is_active", default=True),
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


@dataclass(frozen=True)
class WatchlistHistoryRecord:
    record_id: str
    ticker: str
    action: WatchlistHistoryAction
    reason: str | None
    acted_at: str

    @classmethod
    def create(
        cls,
        *,
        ticker: str,
        action: WatchlistHistoryAction,
        acted_at: str,
        reason: str | None = None,
    ) -> "WatchlistHistoryRecord":
        normalized_ticker = normalize_ticker(ticker)
        normalized_reason = _normalize_reason(reason)
        return cls(
            record_id=f"{normalized_ticker}|{action.value}|{acted_at}",
            ticker=normalized_ticker,
            action=action,
            reason=normalized_reason,
            acted_at=acted_at,
        )

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "WatchlistHistoryRecord":
        raw_reason = data.get("reason")
        return cls(
            record_id=str(data["id"]).strip(),
            ticker=normalize_ticker(str(data["ticker"])),
            action=WatchlistHistoryAction(str(data["action"]).strip().upper()),
            reason=_normalize_reason(raw_reason),
            acted_at=str(data["acted_at"]).strip(),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "id": self.record_id,
            "ticker": self.ticker,
            "action": self.action.value,
            "reason": self.reason,
            "acted_at": self.acted_at,
        }


class WatchlistRepository(Protocol):
    def try_create(self, item: WatchlistItem, *, max_items: int) -> CreateResult:
        """Try creating item atomically with max item constraint."""

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


class WatchlistHistoryRepository(Protocol):
    def append(self, record: WatchlistHistoryRecord) -> None:
        """Append watchlist operation history."""


class WatchlistService:
    def __init__(
        self,
        repository: WatchlistRepository,
        *,
        max_items: int = 100,
        history_repository: WatchlistHistoryRepository | None = None,
    ) -> None:
        if max_items <= 0:
            raise WatchlistError("max_items must be > 0.")
        self._repository = repository
        self._max_items = max_items
        self._history_repository = history_repository

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

    def _record_history(
        self,
        *,
        ticker: str,
        action: WatchlistHistoryAction,
        acted_at: str,
        reason: str | None = None,
    ) -> None:
        if self._history_repository is None:
            return
        self._history_repository.append(
            WatchlistHistoryRecord.create(
                ticker=ticker,
                action=action,
                reason=reason,
                acted_at=acted_at,
            )
        )

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
        reason: str | None = None,
    ) -> WatchlistItem:
        normalized_ticker = normalize_ticker(ticker)

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
        create_result = self._repository.try_create(item, max_items=self._max_items)
        if create_result is CreateResult.DUPLICATE:
            raise WatchlistAlreadyExistsError(f"{normalized_ticker} already exists.")
        if create_result is CreateResult.LIMIT_EXCEEDED:
            raise WatchlistLimitExceededError(f"watchlist limit exceeded: max={self._max_items}")
        if create_result is not CreateResult.CREATED:
            raise WatchlistError(f"unexpected create result: {create_result}")
        try:
            self._record_history(
                ticker=normalized_ticker,
                action=WatchlistHistoryAction.ADD,
                reason=reason,
                acted_at=current_time,
            )
        except Exception as exc:
            rollback_succeeded = False
            try:
                rollback_succeeded = self._repository.delete(normalized_ticker)
            except Exception as rollback_exc:
                raise WatchlistPersistenceError(
                    "watchlist履歴保存に失敗し、watchlist追加のロールバックにも失敗しました。"
                ) from rollback_exc
            if not rollback_succeeded:
                raise WatchlistPersistenceError(
                    "watchlist履歴保存に失敗し、watchlist追加のロールバック対象が見つかりませんでした。"
                ) from exc
            raise WatchlistPersistenceError("watchlist履歴保存に失敗したため、watchlist追加をロールバックしました。") from exc
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

    def delete_item(
        self,
        ticker: str,
        *,
        now_iso: str | None = None,
        reason: str | None = None,
    ) -> None:
        normalized_ticker = normalize_ticker(ticker)
        existing = self._repository.get(normalized_ticker)
        if existing is None:
            raise WatchlistNotFoundError(f"{normalized_ticker} not found.")

        deleted = self._repository.delete(normalized_ticker)
        if not deleted:
            raise WatchlistNotFoundError(f"{normalized_ticker} not found.")
        acted_at = now_iso or self._now_iso()
        try:
            self._record_history(
                ticker=normalized_ticker,
                action=WatchlistHistoryAction.REMOVE,
                reason=reason,
                acted_at=acted_at,
            )
        except Exception as exc:
            try:
                self._repository.create(existing)
            except Exception as rollback_exc:
                raise WatchlistPersistenceError(
                    "watchlist履歴保存に失敗し、watchlist削除のロールバックにも失敗しました。"
                ) from rollback_exc
            raise WatchlistPersistenceError("watchlist履歴保存に失敗したため、watchlist削除をロールバックしました。") from exc


def _coerce_bool(value: Any, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise WatchlistError(f"{field_name} must be boolean-compatible.")


def _normalize_reason(reason: Any) -> str | None:
    if reason is None:
        return None
    normalized = str(reason).strip()
    return normalized or None

from __future__ import annotations

from pydantic import BaseModel, Field

from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem
from kabu_per_bot.watchlist import WatchlistHistoryRecord


class HealthzResponse(BaseModel):
    status: str = Field(default="ok")


class WatchlistItemResponse(BaseModel):
    ticker: str
    name: str
    metric_type: MetricType
    notify_channel: NotifyChannel
    notify_timing: NotifyTiming
    ai_enabled: bool
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_domain(cls, item: WatchlistItem) -> "WatchlistItemResponse":
        return cls(
            ticker=item.ticker,
            name=item.name,
            metric_type=item.metric_type,
            notify_channel=item.notify_channel,
            notify_timing=item.notify_timing,
            ai_enabled=item.ai_enabled,
            is_active=item.is_active,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class WatchlistListResponse(BaseModel):
    items: list[WatchlistItemResponse]
    total: int


class WatchlistCreateRequest(BaseModel):
    ticker: str = Field(pattern=r"^\d{4}:[A-Za-z]+$")
    name: str = Field(min_length=1, max_length=120)
    metric_type: MetricType
    notify_channel: NotifyChannel
    notify_timing: NotifyTiming
    ai_enabled: bool = False
    is_active: bool = True


class WatchlistUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    metric_type: MetricType | None = None
    notify_channel: NotifyChannel | None = None
    notify_timing: NotifyTiming | None = None
    ai_enabled: bool | None = None
    is_active: bool | None = None

    def has_updates(self) -> bool:
        return any(
            (
                self.name is not None,
                self.metric_type is not None,
                self.notify_channel is not None,
                self.notify_timing is not None,
                self.ai_enabled is not None,
                self.is_active is not None,
            )
        )


class DashboardSummaryResponse(BaseModel):
    watchlist_count: int = Field(ge=0, description="監視銘柄数")
    today_notification_count: int = Field(ge=0, description="当日PER/PSR通知件数")
    today_data_unknown_count: int = Field(ge=0, description="当日データ不明件数")
    failed_job_exists: bool = Field(description="失敗ジョブ有無")


class WatchlistHistoryItemResponse(BaseModel):
    record_id: str
    ticker: str
    action: str
    reason: str | None
    acted_at: str

    @classmethod
    def from_domain(cls, record: WatchlistHistoryRecord) -> "WatchlistHistoryItemResponse":
        return cls(
            record_id=record.record_id,
            ticker=record.ticker,
            action=record.action.value,
            reason=record.reason,
            acted_at=record.acted_at,
        )


class WatchlistHistoryListResponse(BaseModel):
    items: list[WatchlistHistoryItemResponse]
    total: int = Field(ge=0)


class NotificationLogItemResponse(BaseModel):
    entry_id: str
    ticker: str
    category: str
    condition_key: str
    sent_at: str
    channel: str
    payload_hash: str
    is_strong: bool

    @classmethod
    def from_domain(cls, entry: NotificationLogEntry) -> "NotificationLogItemResponse":
        return cls(
            entry_id=entry.entry_id,
            ticker=entry.ticker,
            category=entry.category,
            condition_key=entry.condition_key,
            sent_at=entry.sent_at,
            channel=entry.channel,
            payload_hash=entry.payload_hash,
            is_strong=entry.is_strong,
        )


class NotificationLogListResponse(BaseModel):
    items: list[NotificationLogItemResponse]
    total: int = Field(ge=0)

from __future__ import annotations

from pydantic import BaseModel, Field

from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


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

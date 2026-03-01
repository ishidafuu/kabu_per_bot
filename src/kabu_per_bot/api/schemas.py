from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from kabu_per_bot.grok_sns_settings import GrokSnsSettings, validate_grok_sns_settings
from kabu_per_bot.immediate_schedule import ImmediateSchedule, validate_immediate_schedule
from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.watchlist import (
    EvaluationNotifyMode,
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchPriority,
    WatchlistItem,
    XAccountLink,
)
from kabu_per_bot.watchlist import WatchlistHistoryRecord


class HealthzResponse(BaseModel):
    status: str = Field(default="ok")


class WatchlistItemResponse(BaseModel):
    class XAccountLinkResponse(BaseModel):
        handle: str
        role: str | None = None

        @classmethod
        def from_domain(cls, account: XAccountLink) -> "WatchlistItemResponse.XAccountLinkResponse":
            return cls(handle=account.handle, role=account.role)

    ticker: str
    name: str
    metric_type: MetricType
    notify_channel: NotifyChannel
    notify_timing: NotifyTiming
    priority: WatchPriority
    always_notify_enabled: bool
    ai_enabled: bool
    is_active: bool
    evaluation_enabled: bool
    evaluation_notify_mode: EvaluationNotifyMode
    evaluation_top_n: int = Field(ge=1, le=100)
    evaluation_min_strength: int = Field(ge=1, le=5)
    ir_urls: list[str]
    x_official_account: str | None = None
    x_executive_accounts: list[XAccountLinkResponse]
    current_metric_value: float | None = None
    median_1w: float | None = None
    median_3m: float | None = None
    median_1y: float | None = None
    signal_category: str | None = None
    signal_combo: str | None = None
    signal_is_strong: bool | None = None
    signal_streak_days: int | None = None
    notification_skip_reason: str | None = None
    next_earnings_date: str | None = None
    next_earnings_time: str | None = None
    next_earnings_days: int | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_domain(
        cls,
        item: WatchlistItem,
        *,
        current_metric_value: float | None = None,
        median_1w: float | None = None,
        median_3m: float | None = None,
        median_1y: float | None = None,
        signal_category: str | None = None,
        signal_combo: str | None = None,
        signal_is_strong: bool | None = None,
        signal_streak_days: int | None = None,
        notification_skip_reason: str | None = None,
        next_earnings_date: str | None = None,
        next_earnings_time: str | None = None,
        next_earnings_days: int | None = None,
    ) -> "WatchlistItemResponse":
        return cls(
            ticker=item.ticker,
            name=item.name,
            metric_type=item.metric_type,
            notify_channel=item.notify_channel,
            notify_timing=item.notify_timing,
            priority=item.priority,
            always_notify_enabled=item.always_notify_enabled,
            ai_enabled=item.ai_enabled,
            is_active=item.is_active,
            evaluation_enabled=item.evaluation_enabled,
            evaluation_notify_mode=item.evaluation_notify_mode,
            evaluation_top_n=item.evaluation_top_n,
            evaluation_min_strength=item.evaluation_min_strength,
            ir_urls=list(item.ir_urls),
            x_official_account=item.x_official_account,
            x_executive_accounts=[WatchlistItemResponse.XAccountLinkResponse.from_domain(row) for row in item.x_executive_accounts],
            current_metric_value=current_metric_value,
            median_1w=median_1w,
            median_3m=median_3m,
            median_1y=median_1y,
            signal_category=signal_category,
            signal_combo=signal_combo,
            signal_is_strong=signal_is_strong,
            signal_streak_days=signal_streak_days,
            notification_skip_reason=notification_skip_reason,
            next_earnings_date=next_earnings_date,
            next_earnings_time=next_earnings_time,
            next_earnings_days=next_earnings_days,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )


class WatchlistListResponse(BaseModel):
    items: list[WatchlistItemResponse]
    total: int


class WatchlistCreateRequest(BaseModel):
    class XAccountLinkRequest(BaseModel):
        handle: str = Field(min_length=1, max_length=15)
        role: str | None = Field(default=None, max_length=60)

    ticker: str = Field(pattern=r"^\d{4}:[A-Za-z]+$")
    name: str = Field(min_length=1, max_length=120)
    metric_type: MetricType
    notify_channel: NotifyChannel
    notify_timing: NotifyTiming
    priority: WatchPriority = WatchPriority.MEDIUM
    always_notify_enabled: bool = False
    ai_enabled: bool = True
    is_active: bool = True
    evaluation_enabled: bool = False
    evaluation_notify_mode: EvaluationNotifyMode = EvaluationNotifyMode.TOP_N
    evaluation_top_n: int = Field(default=3, ge=1, le=100)
    evaluation_min_strength: int = Field(default=4, ge=1, le=5)
    reason: str | None = Field(default=None, max_length=200)
    ir_urls: list[str] = Field(default_factory=list, max_length=10)
    x_official_account: str | None = Field(default=None, max_length=16)
    x_executive_accounts: list[XAccountLinkRequest] = Field(default_factory=list, max_length=10)

    @field_validator("notify_channel")
    @classmethod
    def validate_notify_channel_fixed(cls, value: NotifyChannel) -> NotifyChannel:
        if value != NotifyChannel.DISCORD:
            raise ValueError("notify_channel は DISCORD 固定です。")
        return value


class WatchlistUpdateRequest(BaseModel):
    class XAccountLinkRequest(BaseModel):
        handle: str = Field(min_length=1, max_length=15)
        role: str | None = Field(default=None, max_length=60)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    metric_type: MetricType | None = None
    notify_channel: NotifyChannel | None = None
    notify_timing: NotifyTiming | None = None
    priority: WatchPriority | None = None
    always_notify_enabled: bool | None = None
    ai_enabled: bool | None = None
    is_active: bool | None = None
    evaluation_enabled: bool | None = None
    evaluation_notify_mode: EvaluationNotifyMode | None = None
    evaluation_top_n: int | None = Field(default=None, ge=1, le=100)
    evaluation_min_strength: int | None = Field(default=None, ge=1, le=5)
    ir_urls: list[str] | None = Field(default=None, max_length=10)
    x_official_account: str | None = Field(default=None, max_length=16)
    x_executive_accounts: list[XAccountLinkRequest] | None = Field(default=None, max_length=10)

    @field_validator("notify_channel")
    @classmethod
    def validate_notify_channel_fixed(cls, value: NotifyChannel | None) -> NotifyChannel | None:
        if value is None:
            return None
        if value != NotifyChannel.DISCORD:
            raise ValueError("notify_channel は DISCORD 固定です。")
        return value

    def has_updates(self) -> bool:
        return any(
            (
                self.name is not None,
                self.metric_type is not None,
                self.notify_channel is not None,
                self.notify_timing is not None,
                self.priority is not None,
                self.always_notify_enabled is not None,
                # 互換性維持: 旧クライアントの ai_enabled 単独PATCHを受け付ける。
                self.ai_enabled is not None,
                self.is_active is not None,
                self.evaluation_enabled is not None,
                self.evaluation_notify_mode is not None,
                self.evaluation_top_n is not None,
                self.evaluation_min_strength is not None,
                self.ir_urls is not None,
                self.x_official_account is not None,
                self.x_executive_accounts is not None,
            )
        )


class IrUrlCandidateSuggestRequest(BaseModel):
    ticker: str = Field(pattern=r"^\d{4}:[A-Za-z]+$")
    company_name: str = Field(min_length=1, max_length=120)
    max_candidates: int = Field(default=5, ge=1, le=10)


class IrUrlCandidateResponse(BaseModel):
    url: str
    title: str
    reason: str
    confidence: str = Field(pattern=r"^(High|Med|Low)$")
    validation_status: str = Field(pattern=r"^(VALID|WARNING|INVALID)$")
    score: int
    http_status: int | None = None
    content_type: str = ""


class IrUrlCandidateListResponse(BaseModel):
    items: list[IrUrlCandidateResponse]
    total: int = Field(ge=0)
    source: str = "VERTEX_AI"


class DashboardSummaryResponse(BaseModel):
    watchlist_count: int = Field(ge=0, description="監視銘柄数")
    today_notification_count: int = Field(ge=0, description="当日PER/PSR通知件数")
    today_data_unknown_count: int = Field(ge=0, description="当日データ不明件数")
    failed_job_exists: bool = Field(description="失敗ジョブ有無")


class AdminOpsJobResponse(BaseModel):
    key: str
    label: str
    job_name: str | None
    configured: bool


class AdminOpsSkipReasonResponse(BaseModel):
    reason: str
    count: int = Field(ge=0)


class AdminOpsExecutionResponse(BaseModel):
    job_key: str
    job_label: str
    job_name: str
    execution_name: str
    status: str
    create_time: str | None
    start_time: str | None
    completion_time: str | None
    message: str | None
    log_uri: str | None
    skip_reasons: list[AdminOpsSkipReasonResponse]
    skip_reason_error: str | None


class AdminOpsSummaryResponse(BaseModel):
    jobs: list[AdminOpsJobResponse]
    recent_executions: list[AdminOpsExecutionResponse]
    latest_skip_reasons: list[AdminOpsExecutionResponse]


class AdminOpsExecutionListResponse(BaseModel):
    items: list[AdminOpsExecutionResponse]


class AdminOpsRunResponse(BaseModel):
    execution: AdminOpsExecutionResponse


class AdminOpsDiscordTestResponse(BaseModel):
    sent_at: str


class AdminOpsGrokCooldownResetResponse(BaseModel):
    reset_at: str
    deleted_entries: int = Field(ge=0)
    deleted_notification_logs: int = Field(ge=0)
    deleted_seen_entries: int = Field(ge=0)
    ticker: str | None = None


class AdminOpsBackfillRequest(BaseModel):
    from_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    to_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    tickers: list[str] = Field(default_factory=list, max_length=100)
    dry_run: bool = True


class AdminImmediateScheduleResponse(BaseModel):
    enabled: bool
    timezone: str
    open_window_start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    open_window_end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    open_window_interval_min: int = Field(ge=1, le=60)
    close_window_start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    close_window_end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    close_window_interval_min: int = Field(ge=1, le=60)

    @classmethod
    def from_domain(cls, value: ImmediateSchedule) -> "AdminImmediateScheduleResponse":
        return cls(
            enabled=value.enabled,
            timezone=value.timezone,
            open_window_start=value.open_window_start,
            open_window_end=value.open_window_end,
            open_window_interval_min=value.open_window_interval_min,
            close_window_start=value.close_window_start,
            close_window_end=value.close_window_end,
            close_window_interval_min=value.close_window_interval_min,
        )


class AdminImmediateScheduleUpdateRequest(BaseModel):
    enabled: bool
    open_window_start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    open_window_end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    open_window_interval_min: int = Field(ge=1, le=60)
    close_window_start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    close_window_end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    close_window_interval_min: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def validate_schedule(self) -> "AdminImmediateScheduleUpdateRequest":
        validate_immediate_schedule(self.to_domain())
        return self

    def to_domain(self) -> ImmediateSchedule:
        return ImmediateSchedule(
            enabled=self.enabled,
            timezone="Asia/Tokyo",
            open_window_start=self.open_window_start,
            open_window_end=self.open_window_end,
            open_window_interval_min=self.open_window_interval_min,
            close_window_start=self.close_window_start,
            close_window_end=self.close_window_end,
            close_window_interval_min=self.close_window_interval_min,
        )


class AdminGrokSnsSettingsResponse(BaseModel):
    enabled: bool
    scheduled_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    per_ticker_cooldown_hours: int = Field(ge=1, le=168)
    prompt_template: str = Field(min_length=20, max_length=4000)

    @classmethod
    def from_domain(cls, value: GrokSnsSettings) -> "AdminGrokSnsSettingsResponse":
        return cls(
            enabled=value.enabled,
            scheduled_time=value.scheduled_time,
            per_ticker_cooldown_hours=value.per_ticker_cooldown_hours,
            prompt_template=value.prompt_template,
        )


class AdminGrokSnsSettingsUpdateRequest(BaseModel):
    enabled: bool
    scheduled_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    per_ticker_cooldown_hours: int = Field(ge=1, le=168)
    prompt_template: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def validate_schedule(self) -> "AdminGrokSnsSettingsUpdateRequest":
        validate_grok_sns_settings(self.to_domain())
        return self

    def to_domain(self) -> GrokSnsSettings:
        return GrokSnsSettings(
            enabled=self.enabled,
            scheduled_time=self.scheduled_time,
            per_ticker_cooldown_hours=self.per_ticker_cooldown_hours,
            prompt_template=self.prompt_template,
        )


class AdminGrokBalanceResponse(BaseModel):
    configured: bool
    available: bool
    amount: float | None = None
    currency: str | None = None
    fetched_at: str | None = None
    error: str | None = None


class AdminGlobalSettingsResponse(BaseModel):
    cooldown_hours: int = Field(ge=1)
    intel_notification_max_age_days: int = Field(ge=1)
    immediate_schedule: AdminImmediateScheduleResponse
    grok_sns: AdminGrokSnsSettingsResponse
    grok_balance: AdminGrokBalanceResponse
    source: str
    updated_at: str | None = None
    updated_by: str | None = None


class AdminGlobalSettingsUpdateRequest(BaseModel):
    cooldown_hours: int | None = Field(default=None, ge=1)
    intel_notification_max_age_days: int | None = Field(default=None, ge=1)
    immediate_schedule: AdminImmediateScheduleUpdateRequest | None = None
    grok_sns: AdminGrokSnsSettingsUpdateRequest | None = None

    @model_validator(mode="after")
    def validate_has_updates(self) -> "AdminGlobalSettingsUpdateRequest":
        if (
            self.cooldown_hours is None
            and self.intel_notification_max_age_days is None
            and self.immediate_schedule is None
            and self.grok_sns is None
        ):
            raise ValueError("at least one setting update is required")
        return self


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


class WatchlistHistoryReasonUpdateRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class WatchlistDetailSummaryResponse(BaseModel):
    last_notification_at: str | None = None
    last_notification_category: str | None = None
    notification_count_7d: int = Field(ge=0)
    strong_notification_count_30d: int = Field(ge=0)
    data_unknown_count_30d: int = Field(ge=0)


class NotificationLogItemResponse(BaseModel):
    entry_id: str
    ticker: str
    category: str
    condition_key: str
    sent_at: str
    channel: str
    payload_hash: str
    is_strong: bool
    body: str | None = None
    data_source: str | None = None
    data_fetched_at: str | None = None

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
            body=entry.body,
            data_source=entry.data_source,
            data_fetched_at=entry.data_fetched_at,
        )


class NotificationLogListResponse(BaseModel):
    items: list[NotificationLogItemResponse]
    total: int = Field(ge=0)


class WatchlistDetailResponse(BaseModel):
    item: WatchlistItemResponse
    summary: WatchlistDetailSummaryResponse
    notifications: NotificationLogListResponse
    history: WatchlistHistoryListResponse

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import logging
from typing import Protocol

from kabu_per_bot.notification import NotificationMessage, format_technical_alert_message
from kabu_per_bot.pipeline import NotificationExecutionMode, PipelineResult
from kabu_per_bot.signal import NotificationLogEntry, evaluate_cooldown
from kabu_per_bot.storage.firestore_schema import normalize_trade_date
from kabu_per_bot.technical import TechnicalAlertRule, TechnicalAlertState, TechnicalIndicatorsDaily
from kabu_per_bot.technical_alerts import (
    build_technical_alert_state,
    describe_technical_alert_threshold,
    evaluate_technical_alert_rule,
)
from kabu_per_bot.technical_profile_runtime import resolve_technical_profile_runtime_settings
from kabu_per_bot.technical_profiles import TechnicalProfile
from kabu_per_bot.watchlist import NotifyChannel, NotifyTiming, WatchlistItem


LOGGER = logging.getLogger(__name__)


class MessageSender(Protocol):
    def send(self, message: str) -> None:
        """Send outbound message."""


class TechnicalIndicatorsDailyRepository(Protocol):
    def get(self, ticker: str, trade_date: str) -> TechnicalIndicatorsDaily | None:
        """Get single indicator row."""

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalIndicatorsDaily]:
        """Get recent indicator rows."""


class TechnicalAlertRulesRepository(Protocol):
    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalAlertRule]:
        """List technical alert rules."""


class TechnicalAlertStateRepository(Protocol):
    def get(self, ticker: str, rule_id: str) -> TechnicalAlertState | None:
        """Get latest alert state."""

    def upsert(self, state: TechnicalAlertState) -> None:
        """Persist alert state."""


class NotificationLogRepository(Protocol):
    def append(self, entry: NotificationLogEntry) -> None:
        """Persist notification log."""

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        """Get recent notification log rows."""


class TechnicalProfilesRepository(Protocol):
    def get(self, profile_id: str) -> TechnicalProfile | None:
        """Get profile by id."""


@dataclass(frozen=True)
class TechnicalAlertPipelineConfig:
    trade_date: str
    cooldown_hours: int
    now_iso: str
    channel: str = "DISCORD"
    execution_mode: NotificationExecutionMode = NotificationExecutionMode.ALL


def run_technical_alert_pipeline(
    *,
    watchlist_items: list[WatchlistItem],
    technical_indicators_repo: TechnicalIndicatorsDailyRepository,
    technical_alert_rules_repo: TechnicalAlertRulesRepository,
    technical_alert_state_repo: TechnicalAlertStateRepository,
    notification_log_repo: NotificationLogRepository,
    technical_profiles_repo: TechnicalProfilesRepository | None,
    sender: MessageSender,
    config: TechnicalAlertPipelineConfig,
) -> PipelineResult:
    result = PipelineResult()
    for item in watchlist_items:
        if not item.is_active:
            continue
        if not _is_channel_enabled(item, config.channel):
            continue
        if not _should_dispatch_for_timing(item.notify_timing, config.execution_mode):
            continue
        try:
            ticker_result = _process_ticker(
                item=item,
                technical_indicators_repo=technical_indicators_repo,
                technical_alert_rules_repo=technical_alert_rules_repo,
                technical_alert_state_repo=technical_alert_state_repo,
                notification_log_repo=notification_log_repo,
                technical_profiles_repo=technical_profiles_repo,
                sender=sender,
                config=config,
            )
        except Exception as exc:
            LOGGER.exception("技術アラート処理失敗: ticker=%s error=%s", item.ticker, exc)
            ticker_result = PipelineResult(processed_tickers=1, errors=1)
        result = result.merge(ticker_result)
    return result


def _process_ticker(
    *,
    item: WatchlistItem,
    technical_indicators_repo: TechnicalIndicatorsDailyRepository,
    technical_alert_rules_repo: TechnicalAlertRulesRepository,
    technical_alert_state_repo: TechnicalAlertStateRepository,
    notification_log_repo: NotificationLogRepository,
    technical_profiles_repo: TechnicalProfilesRepository | None,
    sender: MessageSender,
    config: TechnicalAlertPipelineConfig,
) -> PipelineResult:
    trade_date = normalize_trade_date(config.trade_date)
    current, previous = _load_indicator_pair(
        repository=technical_indicators_repo,
        ticker=item.ticker,
        trade_date=trade_date,
    )
    if current is None:
        LOGGER.info("技術アラートをスキップ: ticker=%s reason=indicator missing trade_date=%s", item.ticker, trade_date)
        return PipelineResult(processed_tickers=1)

    sent = 0
    skipped = 0
    profile = (
        technical_profiles_repo.get(item.technical_profile_id)
        if technical_profiles_repo is not None and item.technical_profile_id is not None
        else None
    )
    runtime = resolve_technical_profile_runtime_settings(
        profile,
        threshold_overrides=item.technical_profile_override_thresholds,
        flag_overrides=item.technical_profile_override_flags,
        strong_alerts_override=item.technical_profile_override_strong_alerts,
        weak_alerts_override=item.technical_profile_override_weak_alerts,
    )
    rules = technical_alert_rules_repo.list_recent(item.ticker, limit=100)
    for rule in rules:
        if not rule.is_active:
            continue
        is_strong = rule.field_key in runtime.strong_alerts
        is_weak = rule.field_key in runtime.weak_alerts
        if runtime.suppress_minor_alerts and is_weak and not is_strong:
            continue
        previous_state = technical_alert_state_repo.get(item.ticker, rule.rule_id)
        evaluation = evaluate_technical_alert_rule(
            rule=rule,
            current=current,
            previous=previous,
            previous_state=previous_state,
        )
        if not evaluation.is_supported:
            LOGGER.warning(
                "技術アラートルールをスキップ: ticker=%s rule_id=%s reason=%s",
                item.ticker,
                rule.rule_id,
                evaluation.invalid_reason,
            )
            continue

        last_triggered_at = previous_state.last_triggered_at if previous_state is not None else None
        if evaluation.should_trigger:
            message = format_technical_alert_message(
                ticker=item.ticker,
                company_name=item.name,
                rule_id=rule.rule_id,
                rule_name=rule.rule_name,
                field_key=rule.field_key,
                trade_date=current.trade_date,
                current_value=evaluation.current_value,
                previous_value=evaluation.previous_value,
                threshold_label=describe_technical_alert_threshold(rule),
                note=rule.note,
            )
            dispatched_sent, dispatched_skipped = _dispatch_with_cooldown(
                message=message,
                ticker=item.ticker,
                notification_log_repo=notification_log_repo,
                sender=sender,
                cooldown_hours=config.cooldown_hours,
                now_iso=config.now_iso,
                channel=config.channel,
                is_strong=is_strong,
            )
            sent += dispatched_sent
            skipped += dispatched_skipped
            if dispatched_sent:
                last_triggered_at = config.now_iso

        technical_alert_state_repo.upsert(
            build_technical_alert_state(
                evaluation=evaluation,
                previous_state=previous_state,
                updated_at=config.now_iso,
                last_triggered_at=last_triggered_at,
            )
        )

    return PipelineResult(processed_tickers=1, sent_notifications=sent, skipped_notifications=skipped)


def _load_indicator_pair(
    *,
    repository: TechnicalIndicatorsDailyRepository,
    ticker: str,
    trade_date: str,
) -> tuple[TechnicalIndicatorsDaily | None, TechnicalIndicatorsDaily | None]:
    current = repository.get(ticker, trade_date)
    rows = repository.list_recent(ticker, limit=3)
    if current is None:
        for row in rows:
            if row.trade_date == trade_date:
                current = row
                break
    if current is None:
        return (None, None)

    previous = None
    for row in rows:
        if row.trade_date < current.trade_date:
            previous = row
            break
    return (current, previous)


def _dispatch_with_cooldown(
    *,
    message: NotificationMessage,
    ticker: str,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    cooldown_hours: int,
    now_iso: str,
    channel: str,
    is_strong: bool,
) -> tuple[int, int]:
    recent = notification_log_repo.list_recent(ticker, limit=100)
    decision = evaluate_cooldown(
        now_iso=now_iso,
        cooldown_hours=cooldown_hours,
        candidate_ticker=ticker,
        candidate_category=message.category,
        candidate_condition_key=message.condition_key,
        candidate_is_strong=is_strong,
        recent_entries=recent,
    )
    if not decision.should_send:
        return (0, 1)

    sender.send(message.body)
    notification_log_repo.append(
        NotificationLogEntry(
            entry_id=_notification_id(message=message, channel=channel, sent_at=now_iso),
            ticker=message.ticker,
            category=message.category,
            condition_key=message.condition_key,
            sent_at=now_iso,
            channel=channel,
            payload_hash=message.payload_hash,
            is_strong=is_strong,
            body=message.body,
        )
    )
    return (1, 0)


def _notification_id(*, message: NotificationMessage, channel: str, sent_at: str) -> str:
    raw = f"{message.ticker}|{message.category}|{message.condition_key}|{channel}|{sent_at}"
    return sha1(raw.encode("utf-8")).hexdigest()


def _is_channel_enabled(item: WatchlistItem, channel: str) -> bool:
    normalized = channel.strip().upper()
    if item.notify_channel is NotifyChannel.OFF:
        return False
    if normalized.startswith("DISCORD"):
        return item.notify_channel is NotifyChannel.DISCORD
    return False


def _should_dispatch_for_timing(
    notify_timing: NotifyTiming,
    execution_mode: NotificationExecutionMode | str,
) -> bool:
    mode = _normalize_execution_mode(execution_mode)
    if notify_timing is NotifyTiming.OFF:
        return False
    if mode is NotificationExecutionMode.ALL:
        return True
    if mode is NotificationExecutionMode.DAILY:
        return notify_timing is NotifyTiming.IMMEDIATE
    return notify_timing is NotifyTiming.AT_21


def _normalize_execution_mode(execution_mode: NotificationExecutionMode | str) -> NotificationExecutionMode:
    if isinstance(execution_mode, NotificationExecutionMode):
        return execution_mode
    try:
        return NotificationExecutionMode(str(execution_mode).strip().upper())
    except ValueError as exc:
        raise ValueError(f"unsupported execution_mode: {execution_mode}") from exc

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha1
import logging
from typing import Protocol

from kabu_per_bot.intelligence import AiAnalyzer, AiAnalyzeError, IntelEvent, IntelKind, IntelSource, IntelSourceError
from kabu_per_bot.notification import (
    NotificationMessage,
    format_ai_attention_message,
    format_data_unknown_message,
    format_intel_update_message,
)
from kabu_per_bot.pipeline import NotificationExecutionMode, PipelineResult
from kabu_per_bot.signal import NotificationLogEntry, evaluate_cooldown
from kabu_per_bot.watchlist import NotifyChannel, NotifyTiming, WatchlistItem


LOGGER = logging.getLogger(__name__)


class MessageSender(Protocol):
    def send(self, message: str) -> None:
        """Send outbound message."""


class NotificationLogRepository(Protocol):
    def append(self, entry: NotificationLogEntry) -> None:
        """Persist notification log."""

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        """Get recent notification log rows."""


class IntelSeenRepository(Protocol):
    def exists(self, fingerprint: str) -> bool:
        """Return whether event was already processed."""

    def has_any_for_ticker(self, ticker: str) -> bool:
        """Return whether ticker already has processed events."""

    def has_any_for_ticker_and_kind(self, ticker: str, kind: IntelKind) -> bool:
        """Return whether ticker already has processed events for kind."""

    def mark_seen(self, event: IntelEvent, *, seen_at: str) -> None:
        """Mark event as processed."""


@dataclass(frozen=True)
class IntelligencePipelineConfig:
    cooldown_hours: int
    now_iso: str
    intel_notification_max_age_days: int = 30
    channel: str = "DISCORD"
    execution_mode: NotificationExecutionMode = NotificationExecutionMode.ALL
    # 互換フィールド。現行運用ではAI要約は常時試行する。
    ai_global_enabled: bool = True


def run_intelligence_pipeline(
    *,
    watchlist_items: list[WatchlistItem],
    source: IntelSource,
    analyzer: AiAnalyzer,
    seen_repo: IntelSeenRepository,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    config: IntelligencePipelineConfig,
) -> PipelineResult:
    if config.intel_notification_max_age_days <= 0:
        raise ValueError("intel_notification_max_age_days must be > 0")

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
                source=source,
                analyzer=analyzer,
                seen_repo=seen_repo,
                notification_log_repo=notification_log_repo,
                sender=sender,
                config=config,
            )
        except Exception as exc:
            LOGGER.exception("IR/SNS処理失敗: ticker=%s error=%s", item.ticker, exc)
            ticker_result = PipelineResult(processed_tickers=1, errors=1)
        result = result.merge(ticker_result)
    return result


def _process_ticker(
    *,
    item: WatchlistItem,
    source: IntelSource,
    analyzer: AiAnalyzer,
    seen_repo: IntelSeenRepository,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    config: IntelligencePipelineConfig,
) -> PipelineResult:
    sent = 0
    skipped = 0
    errors = 0
    is_initial_ir_run = not _has_any_for_ticker_and_kind(
        seen_repo=seen_repo,
        ticker=item.ticker,
        kind=IntelKind.IR,
    )
    try:
        events = source.fetch_events(item, now_iso=config.now_iso)
    except IntelSourceError as exc:
        message = format_data_unknown_message(
            ticker=item.ticker,
            company_name=item.name,
            missing_fields=["ir_sns_source"],
            context=str(exc),
        )
        dispatched_sent, dispatched_skipped = _dispatch_with_cooldown(
            message=message,
            ticker=item.ticker,
            is_strong=False,
            notification_log_repo=notification_log_repo,
            sender=sender,
            cooldown_hours=config.cooldown_hours,
            now_iso=config.now_iso,
            channel=config.channel,
        )
        return PipelineResult(
            processed_tickers=1,
            sent_notifications=dispatched_sent,
            skipped_notifications=dispatched_skipped,
            errors=1,
        )

    for event in events:
        if seen_repo.exists(event.fingerprint):
            continue

        if is_initial_ir_run and event.kind is IntelKind.IR:
            LOGGER.info("IR初回既読化: ticker=%s url=%s", item.ticker, event.url)
            seen_repo.mark_seen(event, seen_at=config.now_iso)
            skipped += 1
            continue

        if not _is_event_recent(
            event=event,
            now_iso=config.now_iso,
            max_age_days=config.intel_notification_max_age_days,
        ):
            LOGGER.info(
                "IR/SNS通知対象外(公開日範囲外): ticker=%s url=%s published_at=%s max_age_days=%s",
                item.ticker,
                event.url,
                event.published_at,
                config.intel_notification_max_age_days,
            )
            seen_repo.mark_seen(event, seen_at=config.now_iso)
            skipped += 1
            continue

        update_message = format_intel_update_message(
            ticker=item.ticker,
            company_name=item.name,
            event=event,
        )
        dispatched_sent, dispatched_skipped = _dispatch_with_cooldown(
            message=update_message,
            ticker=item.ticker,
            is_strong=False,
            notification_log_repo=notification_log_repo,
            sender=sender,
            cooldown_hours=config.cooldown_hours,
            now_iso=config.now_iso,
            channel=config.channel,
        )
        sent += dispatched_sent
        skipped += dispatched_skipped

        try:
            insight = analyzer.analyze(item=item, event=event)
            ai_message = format_ai_attention_message(
                ticker=item.ticker,
                company_name=item.name,
                event=event,
                insight=insight,
            )
            ai_sent, ai_skipped = _dispatch_with_cooldown(
                message=ai_message,
                ticker=item.ticker,
                is_strong=False,
                notification_log_repo=notification_log_repo,
                sender=sender,
                cooldown_hours=config.cooldown_hours,
                now_iso=config.now_iso,
                channel=config.channel,
            )
            sent += ai_sent
            skipped += ai_skipped
        except AiAnalyzeError as exc:
            LOGGER.error("AI解析失敗: ticker=%s url=%s error=%s", item.ticker, event.url, exc)
            errors += 1

        seen_repo.mark_seen(event, seen_at=config.now_iso)

    return PipelineResult(
        processed_tickers=1,
        sent_notifications=sent,
        skipped_notifications=skipped,
        errors=errors,
    )


def _dispatch_with_cooldown(
    *,
    message: NotificationMessage,
    ticker: str,
    is_strong: bool,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    cooldown_hours: int,
    now_iso: str,
    channel: str,
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
    log_entry = NotificationLogEntry(
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
    notification_log_repo.append(log_entry)
    return (1, 0)


def _has_any_for_ticker_and_kind(*, seen_repo: IntelSeenRepository, ticker: str, kind: IntelKind) -> bool:
    typed_lookup = getattr(seen_repo, "has_any_for_ticker_and_kind", None)
    if callable(typed_lookup):
        return bool(typed_lookup(ticker, kind))
    return seen_repo.has_any_for_ticker(ticker)


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


def _is_event_recent(*, event: IntelEvent, now_iso: str, max_age_days: int) -> bool:
    now = _parse_iso_datetime(now_iso)
    published_at = _parse_iso_datetime_or_none(event.published_at)
    if published_at is None:
        # 公開日が取得できないイベントは取りこぼし防止のため通知対象とする。
        return True
    threshold = now - timedelta(days=max_age_days)
    return published_at >= threshold


def _parse_iso_datetime_or_none(value: str) -> datetime | None:
    normalized = str(value).strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_iso_datetime(value: str) -> datetime:
    parsed = _parse_iso_datetime_or_none(value)
    if parsed is None:
        raise ValueError(f"invalid iso datetime: {value}")
    return parsed

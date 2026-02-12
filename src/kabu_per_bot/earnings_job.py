from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from kabu_per_bot.earnings import EarningsCalendarEntry
from kabu_per_bot.pipeline import (
    MessageSender,
    NotificationLogRepository,
    PipelineResult,
    run_tomorrow_earnings_pipeline,
    run_weekly_earnings_pipeline,
)
from kabu_per_bot.watchlist import WatchlistItem


EarningsJobType = Literal["weekly", "tomorrow"]


class WatchlistReader(Protocol):
    def list_all(self) -> list[WatchlistItem]:
        """List all watchlist items."""


class EarningsCalendarReader(Protocol):
    def list_all(self) -> list[EarningsCalendarEntry]:
        """List all earnings calendar rows."""


def resolve_today_jst(*, now_iso: str | None = None, timezone_name: str = "Asia/Tokyo") -> str:
    now = _parse_now_iso(now_iso)
    tz = ZoneInfo(timezone_name)
    return now.astimezone(tz).date().isoformat()


def resolve_now_utc_iso(*, now_iso: str | None = None) -> str:
    now = _parse_now_iso(now_iso)
    return now.astimezone(timezone.utc).isoformat()


def run_earnings_job(
    *,
    job_type: EarningsJobType,
    watchlist_reader: WatchlistReader,
    earnings_reader: EarningsCalendarReader,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    cooldown_hours: int,
    now_iso: str | None = None,
    timezone_name: str = "Asia/Tokyo",
    channel: str = "DISCORD",
) -> PipelineResult:
    today = resolve_today_jst(now_iso=now_iso, timezone_name=timezone_name)
    dispatch_now_iso = resolve_now_utc_iso(now_iso=now_iso)
    watchlist_items = watchlist_reader.list_all()
    earnings_entries = earnings_reader.list_all()

    if job_type == "weekly":
        return run_weekly_earnings_pipeline(
            today=today,
            watchlist_items=watchlist_items,
            earnings_entries=earnings_entries,
            notification_log_repo=notification_log_repo,
            sender=sender,
            cooldown_hours=cooldown_hours,
            now_iso=dispatch_now_iso,
            channel=channel,
        )
    if job_type == "tomorrow":
        return run_tomorrow_earnings_pipeline(
            today=today,
            watchlist_items=watchlist_items,
            earnings_entries=earnings_entries,
            notification_log_repo=notification_log_repo,
            sender=sender,
            cooldown_hours=cooldown_hours,
            now_iso=dispatch_now_iso,
            channel=channel,
        )
    raise ValueError(f"unsupported job_type: {job_type}")


def _parse_now_iso(now_iso: str | None) -> datetime:
    if now_iso is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(now_iso)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from kabu_per_bot.api.dependencies import NotificationLogReader, get_notification_log_repository, get_watchlist_service
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import CommitteeLogSummaryResponse, NotificationLogItemResponse, NotificationLogListResponse
from kabu_per_bot.watchlist import WatchPriority, WatchlistService

router = APIRouter(
    prefix="/notifications",
    tags=["notification-logs"],
)


@router.get(
    "/logs",
    response_model=NotificationLogListResponse,
    responses=error_responses(401, 403, 422, 500),
)
def list_notification_logs(
    ticker: str | None = Query(default=None, pattern=r"^\d{4}:[Tt][Ss][Ee]$"),
    priority: WatchPriority | None = Query(default=None),
    category: str | None = Query(default=None, max_length=64),
    strong_only: bool = Query(default=False),
    evaluation_confidence_min: int | None = Query(default=None, ge=1, le=5),
    evaluation_strength_min: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repository: NotificationLogReader = Depends(get_notification_log_repository),
    watchlist_service: WatchlistService = Depends(get_watchlist_service),
) -> NotificationLogListResponse:
    is_strong_filter = True if strong_only else None
    has_score_filter = evaluation_confidence_min is not None or evaluation_strength_min is not None
    if priority is None and not has_score_filter:
        rows = repository.list_timeline(
            ticker=ticker,
            category=category,
            is_strong=is_strong_filter,
            limit=limit,
            offset=offset,
        )
        total = repository.count_timeline(
            ticker=ticker,
            category=category,
            is_strong=is_strong_filter,
        )
    else:
        watchlist_priorities = (
            {item.ticker: item.priority for item in watchlist_service.list_items()}
            if priority is not None
            else {}
        )
        all_rows = repository.list_timeline(
            ticker=ticker,
            category=category,
            is_strong=is_strong_filter,
            limit=None,
            offset=0,
        )
        filtered = all_rows
        if priority is not None:
            filtered = [row for row in filtered if watchlist_priorities.get(row.ticker) == priority]
        if evaluation_confidence_min is not None:
            filtered = [
                row
                for row in filtered
                if row.evaluation_confidence is not None and row.evaluation_confidence >= evaluation_confidence_min
            ]
        if evaluation_strength_min is not None:
            filtered = [
                row
                for row in filtered
                if row.evaluation_strength is not None and row.evaluation_strength >= evaluation_strength_min
            ]
        total = len(filtered)
        rows = filtered[offset : offset + limit]

    return NotificationLogListResponse(
        items=[NotificationLogItemResponse.from_domain(row) for row in rows],
        total=total,
    )


@router.get(
    "/logs/committee-summary",
    response_model=CommitteeLogSummaryResponse,
    responses=error_responses(401, 403, 422, 500),
)
def summarize_committee_logs(
    days: int = Query(default=7, ge=1, le=30),
    repository: NotificationLogReader = Depends(get_notification_log_repository),
) -> CommitteeLogSummaryResponse:
    sent_at_from = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = repository.list_timeline(
        category="委員会評価",
        sent_at_from=sent_at_from,
        limit=None,
        offset=0,
    )

    confidence_distribution = {str(score): 0 for score in range(1, 6)}
    strength_distribution = {str(score): 0 for score in range(1, 6)}
    lens_hit_counts = {
        "business": 0,
        "financial": 0,
        "valuation": 0,
        "technical": 0,
        "event": 0,
        "risk": 0,
    }
    for row in rows:
        if row.evaluation_confidence is not None:
            key = str(row.evaluation_confidence)
            if key in confidence_distribution:
                confidence_distribution[key] += 1
        if row.evaluation_strength is not None:
            key = str(row.evaluation_strength)
            if key in strength_distribution:
                strength_distribution[key] += 1
        if row.evaluation_lens_strengths:
            for lens_key, score in row.evaluation_lens_strengths.items():
                if lens_key not in lens_hit_counts:
                    continue
                if score >= 4:
                    lens_hit_counts[lens_key] += 1

    return CommitteeLogSummaryResponse(
        total=len(rows),
        lens_hit_counts=lens_hit_counts,
        confidence_distribution=confidence_distribution,
        strength_distribution=strength_distribution,
    )

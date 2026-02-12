from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from kabu_per_bot.api.dependencies import NotificationLogReader, get_notification_log_repository, get_watchlist_service
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import DashboardSummaryResponse
from kabu_per_bot.watchlist import WatchlistService

JST = ZoneInfo("Asia/Tokyo")

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
)


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    responses=error_responses(401, 403, 500),
)
def get_dashboard_summary(
    service: WatchlistService = Depends(get_watchlist_service),
    notification_log_repo: NotificationLogReader = Depends(get_notification_log_repository),
) -> DashboardSummaryResponse:
    watchlist_count = len(service.list_items())
    now_jst = datetime.now(timezone.utc).astimezone(JST)
    today_start_jst = now_jst.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start_jst = today_start_jst + timedelta(days=1)
    sent_at_from = today_start_jst.astimezone(timezone.utc).isoformat()
    sent_at_to = tomorrow_start_jst.astimezone(timezone.utc).isoformat()

    today_notification_count = 0
    today_data_unknown_count = 0
    for entry in notification_log_repo.list_timeline(
        sent_at_from=sent_at_from,
        sent_at_to=sent_at_to,
        limit=None,
    ):
        if entry.category == "データ不明":
            today_data_unknown_count += 1
            continue
        if entry.condition_key.startswith(("PER:", "PSR:")):
            today_notification_count += 1

    failed_job_exists = notification_log_repo.failed_job_exists(
        sent_at_from=sent_at_from,
        sent_at_to=sent_at_to,
    )

    return DashboardSummaryResponse(
        watchlist_count=watchlist_count,
        today_notification_count=today_notification_count,
        today_data_unknown_count=today_data_unknown_count,
        failed_job_exists=failed_job_exists,
    )

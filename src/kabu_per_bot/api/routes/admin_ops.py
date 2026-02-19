from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from kabu_per_bot.admin_ops import (
    AdminOpsConfigError,
    AdminOpsConflictError,
    AdminOpsNotFoundError,
    BackfillRunRequest,
    JobExecution,
    SkipReasonCount,
)
from kabu_per_bot.api.dependencies import (
    AdminOpsReader,
    NotificationLogReader,
    get_admin_ops_service,
    get_authenticated_uid,
    get_notification_log_repository,
    require_admin_user,
)
from kabu_per_bot.api.errors import BadRequestError, ConflictError, InternalServerError, NotFoundError
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import (
    AdminOpsBackfillRequest,
    AdminOpsGrokCooldownResetResponse,
    AdminOpsDiscordTestResponse,
    AdminOpsExecutionListResponse,
    AdminOpsExecutionResponse,
    AdminOpsJobResponse,
    AdminOpsRunResponse,
    AdminOpsSkipReasonResponse,
    AdminOpsSummaryResponse,
)

router = APIRouter(
    prefix="/admin/ops",
    tags=["admin-ops"],
    dependencies=[Depends(require_admin_user)],
)


@router.get(
    "/summary",
    response_model=AdminOpsSummaryResponse,
    responses=error_responses(401, 403, 500),
)
def get_admin_ops_summary(
    limit_per_job: int = Query(default=5, ge=1, le=50),
    include_recent_executions: bool = Query(default=True),
    include_skip_reasons: bool = Query(default=True),
    service: AdminOpsReader = Depends(get_admin_ops_service),
) -> AdminOpsSummaryResponse:
    try:
        summary = service.get_summary(
            limit_per_job=limit_per_job,
            include_recent_executions=include_recent_executions,
            include_skip_reasons=include_skip_reasons,
        )
    except Exception as exc:
        raise InternalServerError(f"管理運用サマリーの取得に失敗しました: {exc}") from exc
    return AdminOpsSummaryResponse(
        jobs=[
            AdminOpsJobResponse(
                key=row.key,
                label=row.label,
                job_name=row.job_name,
                configured=row.configured,
            )
            for row in summary.jobs
        ],
        recent_executions=[_to_execution_response(row) for row in summary.recent_executions],
        latest_skip_reasons=[_to_execution_response(row) for row in summary.latest_skip_reasons],
    )


@router.get(
    "/jobs/{job_key}/executions",
    response_model=AdminOpsExecutionListResponse,
    responses=error_responses(400, 401, 403, 404, 500),
)
def list_admin_job_executions(
    job_key: str,
    limit: int = Query(default=20, ge=1, le=50),
    service: AdminOpsReader = Depends(get_admin_ops_service),
) -> AdminOpsExecutionListResponse:
    try:
        rows = service.list_executions(job_key=job_key, limit=limit)
    except AdminOpsNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except AdminOpsConfigError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise InternalServerError(f"実行履歴の取得に失敗しました: {exc}") from exc
    return AdminOpsExecutionListResponse(items=[_to_execution_response(row) for row in rows])


@router.post(
    "/jobs/{job_key}/run",
    response_model=AdminOpsRunResponse,
    responses=error_responses(400, 401, 403, 404, 409, 500),
)
def run_admin_job(
    job_key: str,
    payload: AdminOpsBackfillRequest | None = None,
    service: AdminOpsReader = Depends(get_admin_ops_service),
) -> AdminOpsRunResponse:
    backfill_request = None
    if payload is not None:
        backfill_request = BackfillRunRequest(
            from_date=payload.from_date,
            to_date=payload.to_date,
            tickers=tuple(payload.tickers),
            dry_run=payload.dry_run,
        )
    try:
        execution = service.run_job(job_key=job_key, backfill=backfill_request)
    except AdminOpsNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except AdminOpsConflictError as exc:
        raise ConflictError(str(exc)) from exc
    except AdminOpsConfigError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise InternalServerError(f"ジョブ実行に失敗しました: {exc}") from exc
    return AdminOpsRunResponse(execution=_to_execution_response(execution))


@router.post(
    "/discord/test",
    response_model=AdminOpsDiscordTestResponse,
    responses=error_responses(400, 401, 403, 500),
)
def send_discord_test_notification(
    uid: str = Depends(get_authenticated_uid),
    service: AdminOpsReader = Depends(get_admin_ops_service),
) -> AdminOpsDiscordTestResponse:
    try:
        sent_at = service.send_discord_test(requested_uid=uid)
    except AdminOpsConfigError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise InternalServerError(f"Discord疎通テストに失敗しました: {exc}") from exc
    return AdminOpsDiscordTestResponse(sent_at=sent_at)


@router.post(
    "/grok/cooldown/reset",
    response_model=AdminOpsGrokCooldownResetResponse,
    responses=error_responses(400, 401, 403, 500),
)
def reset_grok_cooldown(
    ticker: str | None = Query(default=None),
    notification_log_repository: NotificationLogReader = Depends(get_notification_log_repository),
) -> AdminOpsGrokCooldownResetResponse:
    normalized_ticker: str | None = None
    if ticker is not None and ticker.strip():
        candidate = ticker.strip().upper()
        if len(candidate) != 8 or candidate[4:] != ":TSE" or not candidate[:4].isdigit():
            raise BadRequestError("ticker は 1234:TSE 形式で指定してください。")
        normalized_ticker = candidate
    try:
        deleted = notification_log_repository.reset_grok_sns_cooldown(ticker=normalized_ticker)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise InternalServerError(f"Grokクールダウンのリセットに失敗しました: {exc}") from exc
    return AdminOpsGrokCooldownResetResponse(
        reset_at=datetime.now(timezone.utc).isoformat(),
        deleted_entries=deleted,
        ticker=normalized_ticker,
    )


def _to_execution_response(row: JobExecution) -> AdminOpsExecutionResponse:
    return AdminOpsExecutionResponse(
        job_key=row.job_key,
        job_label=row.job_label,
        job_name=row.job_name,
        execution_name=row.execution_name,
        status=row.status,
        create_time=row.create_time,
        start_time=row.start_time,
        completion_time=row.completion_time,
        message=row.message,
        log_uri=row.log_uri,
        skip_reasons=[_to_skip_reason_response(item) for item in row.skip_reasons],
        skip_reason_error=row.skip_reason_error,
    )


def _to_skip_reason_response(row: SkipReasonCount) -> AdminOpsSkipReasonResponse:
    return AdminOpsSkipReasonResponse(reason=row.reason, count=row.count)

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from kabu_per_bot.api.dependencies import (
    GlobalSettingsRepository,
    get_authenticated_uid,
    get_global_settings_repository,
    require_admin_user,
)
from kabu_per_bot.api.errors import InternalServerError
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import (
    AdminGrokBalanceResponse,
    AdminGlobalSettingsResponse,
    AdminGrokSnsSettingsResponse,
    AdminGlobalSettingsUpdateRequest,
    AdminImmediateScheduleResponse,
)
from kabu_per_bot.grok_billing import fetch_prepaid_balance
from kabu_per_bot.grok_sns_settings import GrokSnsSettings
from kabu_per_bot.immediate_schedule import ImmediateSchedule
from kabu_per_bot.runtime_settings import resolve_runtime_settings
from kabu_per_bot.settings import load_settings

router = APIRouter(
    prefix="/admin/settings",
    tags=["admin-settings"],
    dependencies=[Depends(require_admin_user)],
)


@router.get(
    "/global",
    response_model=AdminGlobalSettingsResponse,
    responses=error_responses(401, 403, 500),
)
def get_admin_global_settings(
    repository: GlobalSettingsRepository = Depends(get_global_settings_repository),
) -> AdminGlobalSettingsResponse:
    try:
        return _build_global_settings_response(repository=repository)
    except Exception as exc:
        raise InternalServerError(f"全体設定の取得に失敗しました: {exc}") from exc


@router.patch(
    "/global",
    response_model=AdminGlobalSettingsResponse,
    responses=error_responses(401, 403, 500),
)
def update_admin_global_settings(
    payload: AdminGlobalSettingsUpdateRequest,
    uid: str = Depends(get_authenticated_uid),
    repository: GlobalSettingsRepository = Depends(get_global_settings_repository),
) -> AdminGlobalSettingsResponse:
    try:
        immediate_schedule: ImmediateSchedule | None = None
        grok_sns_settings: GrokSnsSettings | None = None
        if payload.immediate_schedule is not None:
            immediate_schedule = payload.immediate_schedule.to_domain()
        if payload.grok_sns is not None:
            grok_sns_settings = payload.grok_sns.to_domain()
        repository.upsert_global_settings(
            cooldown_hours=payload.cooldown_hours,
            intel_notification_max_age_days=payload.intel_notification_max_age_days,
            immediate_schedule=immediate_schedule,
            grok_sns_settings=grok_sns_settings,
            updated_at=datetime.now(timezone.utc).isoformat(),
            updated_by=uid,
        )
        return _build_global_settings_response(repository=repository)
    except Exception as exc:
        raise InternalServerError(f"全体設定の更新に失敗しました: {exc}") from exc


def _build_global_settings_response(*, repository: GlobalSettingsRepository) -> AdminGlobalSettingsResponse:
    app_settings = load_settings()
    grok_balance = fetch_prepaid_balance(
        api_key=app_settings.grok_management_api_key,
        team_id=app_settings.grok_management_team_id,
        base_url=app_settings.grok_management_api_base_url,
    )
    global_settings = repository.get_global_settings()
    runtime_settings = resolve_runtime_settings(
        default_cooldown_hours=app_settings.cooldown_hours,
        default_intel_notification_max_age_days=app_settings.intel_notification_max_age_days,
        default_grok_sns_settings=GrokSnsSettings(
            enabled=app_settings.grok_sns_enabled,
            scheduled_time=app_settings.grok_sns_scheduled_time,
            per_ticker_cooldown_hours=app_settings.grok_sns_per_ticker_cooldown_hours,
            prompt_template=app_settings.grok_sns_prompt_template,
        ),
        global_settings=global_settings,
    )
    return AdminGlobalSettingsResponse(
        cooldown_hours=runtime_settings.cooldown_hours,
        intel_notification_max_age_days=runtime_settings.intel_notification_max_age_days,
        immediate_schedule=AdminImmediateScheduleResponse.from_domain(runtime_settings.immediate_schedule),
        grok_sns=AdminGrokSnsSettingsResponse.from_domain(runtime_settings.grok_sns_settings),
        grok_balance=AdminGrokBalanceResponse(
            configured=grok_balance.configured,
            available=grok_balance.available,
            amount=grok_balance.amount,
            currency=grok_balance.currency,
            fetched_at=grok_balance.fetched_at,
            error=grok_balance.error,
        ),
        source=runtime_settings.source,
        updated_at=runtime_settings.updated_at,
        updated_by=runtime_settings.updated_by,
    )

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
from kabu_per_bot.api.schemas import AdminGlobalSettingsResponse, AdminGlobalSettingsUpdateRequest
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
        repository.upsert_global_settings(
            cooldown_hours=payload.cooldown_hours,
            updated_at=datetime.now(timezone.utc).isoformat(),
            updated_by=uid,
        )
        return _build_global_settings_response(repository=repository)
    except Exception as exc:
        raise InternalServerError(f"全体設定の更新に失敗しました: {exc}") from exc


def _build_global_settings_response(*, repository: GlobalSettingsRepository) -> AdminGlobalSettingsResponse:
    app_settings = load_settings()
    global_settings = repository.get_global_settings()
    runtime_settings = resolve_runtime_settings(
        default_cooldown_hours=app_settings.cooldown_hours,
        global_settings=global_settings,
    )
    return AdminGlobalSettingsResponse(
        cooldown_hours=runtime_settings.cooldown_hours,
        source=runtime_settings.source,
        updated_at=runtime_settings.updated_at,
        updated_by=runtime_settings.updated_by,
    )

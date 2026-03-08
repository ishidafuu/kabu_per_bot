from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from kabu_per_bot.api.dependencies import (
    TechnicalProfilesReader,
    get_technical_profiles_repository,
    require_admin_user,
)
from kabu_per_bot.api.errors import BadRequestError, ConflictError, InternalServerError, NotFoundError
from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import (
    TechnicalProfileCloneRequest,
    TechnicalProfileCreateRequest,
    TechnicalProfileListResponse,
    TechnicalProfileResponse,
    TechnicalProfileUpdateRequest,
)
from kabu_per_bot.technical_profiles import TechnicalProfile, TechnicalProfileType


router = APIRouter(
    prefix="/technical-profiles",
    tags=["technical-profiles"],
    dependencies=[Depends(require_admin_user)],
)


@router.get(
    "",
    response_model=TechnicalProfileListResponse,
    responses=error_responses(401, 403, 500),
)
def list_technical_profiles(
    repository: TechnicalProfilesReader = Depends(get_technical_profiles_repository),
) -> TechnicalProfileListResponse:
    try:
        items = [TechnicalProfileResponse.from_domain(profile) for profile in repository.list_all(include_inactive=True)]
        return TechnicalProfileListResponse(items=items, total=len(items))
    except Exception as exc:
        raise InternalServerError(f"technical profile 一覧の取得に失敗しました: {exc}") from exc


@router.get(
    "/{profile_id}",
    response_model=TechnicalProfileResponse,
    responses=error_responses(401, 403, 404, 500),
)
def get_technical_profile(
    profile_id: str,
    repository: TechnicalProfilesReader = Depends(get_technical_profiles_repository),
) -> TechnicalProfileResponse:
    try:
        profile = repository.get(profile_id)
        if profile is None:
            raise NotFoundError("technical profile が見つかりません。")
        return TechnicalProfileResponse.from_domain(profile)
    except NotFoundError:
        raise
    except Exception as exc:
        raise InternalServerError(f"technical profile の取得に失敗しました: {exc}") from exc


@router.post(
    "",
    response_model=TechnicalProfileResponse,
    responses=error_responses(401, 403, 409, 500),
)
def create_technical_profile(
    payload: TechnicalProfileCreateRequest,
    repository: TechnicalProfilesReader = Depends(get_technical_profiles_repository),
) -> TechnicalProfileResponse:
    try:
        profile_key = _normalize_profile_key(payload.profile_key)
        _ensure_profile_key_is_available(repository=repository, profile_key=profile_key)
        now = _utc_now()
        profile = TechnicalProfile(
            profile_id=f"custom_{profile_key}",
            profile_type=TechnicalProfileType.CUSTOM,
            profile_key=profile_key,
            name=payload.name,
            description=payload.description,
            base_profile_key=payload.base_profile_key,
            priority_order=payload.priority_order,
            manual_assign_recommended=payload.manual_assign_recommended,
            auto_assign=payload.auto_assign,
            thresholds=payload.thresholds,
            weights=payload.weights,
            flags=payload.flags,
            strong_alerts=tuple(payload.strong_alerts),
            weak_alerts=tuple(payload.weak_alerts),
            is_active=payload.is_active,
            created_at=now,
            updated_at=now,
        )
        repository.upsert(profile)
        return TechnicalProfileResponse.from_domain(profile)
    except ConflictError:
        raise
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise InternalServerError(f"technical profile の作成に失敗しました: {exc}") from exc


@router.post(
    "/{profile_id}/clone",
    response_model=TechnicalProfileResponse,
    responses=error_responses(401, 403, 404, 409, 500),
)
def clone_technical_profile(
    profile_id: str,
    payload: TechnicalProfileCloneRequest,
    repository: TechnicalProfilesReader = Depends(get_technical_profiles_repository),
) -> TechnicalProfileResponse:
    try:
        source = repository.get(profile_id)
        if source is None:
            raise NotFoundError("technical profile が見つかりません。")
        profile_key = _normalize_profile_key(payload.profile_key)
        _ensure_profile_key_is_available(repository=repository, profile_key=profile_key)
        now = _utc_now()
        profile = TechnicalProfile(
            profile_id=f"custom_{profile_key}",
            profile_type=TechnicalProfileType.CUSTOM,
            profile_key=profile_key,
            name=payload.name,
            description=payload.description or source.description,
            base_profile_key=source.profile_key,
            priority_order=source.priority_order,
            manual_assign_recommended=source.manual_assign_recommended,
            auto_assign=source.auto_assign,
            thresholds=source.thresholds,
            weights=source.weights,
            flags=source.flags,
            strong_alerts=source.strong_alerts,
            weak_alerts=source.weak_alerts,
            is_active=source.is_active,
            created_at=now,
            updated_at=now,
        )
        repository.upsert(profile)
        return TechnicalProfileResponse.from_domain(profile)
    except (NotFoundError, ConflictError):
        raise
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise InternalServerError(f"technical profile の複製に失敗しました: {exc}") from exc


@router.patch(
    "/{profile_id}",
    response_model=TechnicalProfileResponse,
    responses=error_responses(401, 403, 404, 409, 500),
)
def update_technical_profile(
    profile_id: str,
    payload: TechnicalProfileUpdateRequest,
    repository: TechnicalProfilesReader = Depends(get_technical_profiles_repository),
) -> TechnicalProfileResponse:
    try:
        current = repository.get(profile_id)
        if current is None:
            raise NotFoundError("technical profile が見つかりません。")
        if current.profile_type == TechnicalProfileType.SYSTEM:
            raise ConflictError("SYSTEM profile は編集できません。")
        updated = replace(
            current,
            name=payload.name if payload.name is not None else current.name,
            description=payload.description if payload.description is not None else current.description,
            priority_order=payload.priority_order if payload.priority_order is not None else current.priority_order,
            manual_assign_recommended=(
                payload.manual_assign_recommended
                if payload.manual_assign_recommended is not None
                else current.manual_assign_recommended
            ),
            auto_assign=payload.auto_assign if payload.auto_assign is not None else current.auto_assign,
            thresholds=payload.thresholds if payload.thresholds is not None else current.thresholds,
            weights=payload.weights if payload.weights is not None else current.weights,
            flags=payload.flags if payload.flags is not None else current.flags,
            strong_alerts=tuple(payload.strong_alerts) if payload.strong_alerts is not None else current.strong_alerts,
            weak_alerts=tuple(payload.weak_alerts) if payload.weak_alerts is not None else current.weak_alerts,
            is_active=payload.is_active if payload.is_active is not None else current.is_active,
            updated_at=_utc_now(),
        )
        repository.upsert(updated)
        return TechnicalProfileResponse.from_domain(updated)
    except (NotFoundError, ConflictError):
        raise
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:
        raise InternalServerError(f"technical profile の更新に失敗しました: {exc}") from exc


def _ensure_profile_key_is_available(*, repository: TechnicalProfilesReader, profile_key: str) -> None:
    for profile in repository.list_all(include_inactive=True):
        if profile.profile_key == profile_key:
            raise ConflictError("profile_key は既に使用されています。")


def _normalize_profile_key(value: str) -> str:
    normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if not normalized:
        raise ValueError("profile_key is required")
    return normalized


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

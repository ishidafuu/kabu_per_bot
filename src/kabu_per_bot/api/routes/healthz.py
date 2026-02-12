from fastapi import APIRouter

from kabu_per_bot.api.openapi import error_responses
from kabu_per_bot.api.schemas import HealthzResponse

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthzResponse, responses=error_responses(500))
def healthz() -> HealthzResponse:
    return HealthzResponse(status="ok")

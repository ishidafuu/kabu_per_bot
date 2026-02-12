from fastapi import APIRouter

from kabu_per_bot.api.routes.healthz import router as healthz_router
from kabu_per_bot.api.routes.watchlist import router as watchlist_router

api_router = APIRouter()
api_router.include_router(healthz_router)
api_router.include_router(watchlist_router)

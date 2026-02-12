from fastapi import APIRouter

from kabu_per_bot.api.routes.dashboard import router as dashboard_router
from kabu_per_bot.api.routes.healthz import router as healthz_router
from kabu_per_bot.api.routes.notification_logs import router as notification_logs_router
from kabu_per_bot.api.routes.watchlist import router as watchlist_router
from kabu_per_bot.api.routes.watchlist_history import router as watchlist_history_router

api_router = APIRouter()
api_router.include_router(healthz_router)
api_router.include_router(dashboard_router)
api_router.include_router(watchlist_history_router)
api_router.include_router(notification_logs_router)
api_router.include_router(watchlist_router)

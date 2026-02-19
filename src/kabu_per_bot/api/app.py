from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kabu_per_bot.api.auth import FirebaseAdminTokenVerifier, TokenVerifier
from kabu_per_bot.api.dependencies import (
    AdminOpsReader,
    DailyMetricsReader,
    EarningsCalendarReader,
    GlobalSettingsRepository,
    IrUrlCandidateReader,
    IntelSeenReader,
    MetricMediansReader,
    NotificationLogReader,
    SignalStateReader,
    WatchlistHistoryReader,
    create_daily_metrics_repository,
    create_earnings_calendar_repository,
    create_admin_ops_service,
    create_intel_seen_repository,
    create_ir_url_candidate_service,
    create_metric_medians_repository,
    create_notification_log_repository,
    create_global_settings_repository,
    create_signal_state_repository,
    create_watchlist_history_repository,
    create_watchlist_service,
)
from kabu_per_bot.api.errors import install_exception_handlers
from kabu_per_bot.api.middleware import install_auth_middleware
from kabu_per_bot.api.routes import api_router
from kabu_per_bot.watchlist import WatchlistService


def create_app(
    *,
    watchlist_service: WatchlistService | None = None,
    watchlist_history_repository: WatchlistHistoryReader | None = None,
    notification_log_repository: NotificationLogReader | None = None,
    intel_seen_repository: IntelSeenReader | None = None,
    daily_metrics_repository: DailyMetricsReader | None = None,
    metric_medians_repository: MetricMediansReader | None = None,
    signal_state_repository: SignalStateReader | None = None,
    earnings_calendar_repository: EarningsCalendarReader | None = None,
    admin_ops_service: AdminOpsReader | None = None,
    global_settings_repository: GlobalSettingsRepository | None = None,
    ir_url_candidate_service: IrUrlCandidateReader | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastAPI:
    app = FastAPI(
        title="kabu_per_bot Web API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://kabu-per-bot-487501.web.app",
            "http://localhost:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(app)

    app.state.watchlist_service = watchlist_service
    app.state.watchlist_service_factory = create_watchlist_service

    app.state.watchlist_history_repository = watchlist_history_repository
    app.state.watchlist_history_repository_factory = create_watchlist_history_repository

    app.state.notification_log_repository = notification_log_repository
    app.state.notification_log_repository_factory = create_notification_log_repository

    app.state.intel_seen_repository = intel_seen_repository
    app.state.intel_seen_repository_factory = create_intel_seen_repository

    app.state.daily_metrics_repository = daily_metrics_repository
    app.state.daily_metrics_repository_factory = create_daily_metrics_repository

    app.state.metric_medians_repository = metric_medians_repository
    app.state.metric_medians_repository_factory = create_metric_medians_repository

    app.state.signal_state_repository = signal_state_repository
    app.state.signal_state_repository_factory = create_signal_state_repository

    app.state.earnings_calendar_repository = earnings_calendar_repository
    app.state.earnings_calendar_repository_factory = create_earnings_calendar_repository

    app.state.admin_ops_service = admin_ops_service
    app.state.admin_ops_service_factory = create_admin_ops_service

    app.state.global_settings_repository = global_settings_repository
    app.state.global_settings_repository_factory = create_global_settings_repository

    app.state.ir_url_candidate_service = ir_url_candidate_service
    app.state.ir_url_candidate_service_factory = create_ir_url_candidate_service

    app.state.token_verifier = token_verifier
    app.state.token_verifier_factory = _default_token_verifier_factory

    install_auth_middleware(app)
    app.include_router(api_router, prefix="/api/v1")
    return app


def _default_token_verifier_factory() -> TokenVerifier:
    return FirebaseAdminTokenVerifier()


app = create_app()

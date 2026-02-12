from __future__ import annotations

from fastapi import FastAPI

from kabu_per_bot.api.auth import FirebaseAdminTokenVerifier, TokenVerifier
from kabu_per_bot.api.dependencies import create_watchlist_service
from kabu_per_bot.api.errors import install_exception_handlers
from kabu_per_bot.api.middleware import install_auth_middleware
from kabu_per_bot.api.routes import api_router
from kabu_per_bot.watchlist import WatchlistService


def create_app(
    *,
    watchlist_service: WatchlistService | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastAPI:
    app = FastAPI(
        title="kabu_per_bot Web API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    install_exception_handlers(app)

    app.state.watchlist_service = watchlist_service
    app.state.watchlist_service_factory = create_watchlist_service

    app.state.token_verifier = token_verifier
    app.state.token_verifier_factory = _default_token_verifier_factory

    install_auth_middleware(app)
    app.include_router(api_router, prefix="/api/v1")
    return app


def _default_token_verifier_factory() -> TokenVerifier:
    return FirebaseAdminTokenVerifier()


app = create_app()

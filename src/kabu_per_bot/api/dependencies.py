from __future__ import annotations

from typing import Callable

from fastapi import Request

from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository
from kabu_per_bot.watchlist import WatchlistService


def create_watchlist_service() -> WatchlistService:
    settings = load_settings()
    try:
        from google.cloud import firestore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-cloud-firestore が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc

    project = settings.firestore_project_id or None
    client = firestore.Client(project=project)
    repository = FirestoreWatchlistRepository(client)
    return WatchlistService(repository, max_items=100)


def get_watchlist_service(request: Request) -> WatchlistService:
    service = getattr(request.app.state, "watchlist_service", None)
    if service is not None:
        return service

    factory: Callable[[], WatchlistService] | None = getattr(request.app.state, "watchlist_service_factory", None)
    if factory is None:
        raise RuntimeError("watchlist_service が初期化されていません。")
    service = factory()
    request.app.state.watchlist_service = service
    return service

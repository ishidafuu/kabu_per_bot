from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar

from fastapi import Request

from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_notification_log_repository import FirestoreNotificationLogRepository
from kabu_per_bot.storage.firestore_watchlist_history_repository import FirestoreWatchlistHistoryRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository
from kabu_per_bot.watchlist import WatchlistHistoryRecord, WatchlistService


class WatchlistHistoryReader(Protocol):
    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[WatchlistHistoryRecord]:
        """List watchlist history in descending chronological order."""

    def count_timeline(
        self,
        *,
        ticker: str | None = None,
    ) -> int:
        """Count watchlist history rows."""


class NotificationLogReader(Protocol):
    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> list[NotificationLogEntry]:
        """List notification logs in descending chronological order."""

    def count_timeline(
        self,
        *,
        ticker: str | None = None,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> int:
        """Count notification logs."""

    def failed_job_exists(
        self,
        *,
        sent_at_from: str,
        sent_at_to: str,
    ) -> bool | None:
        """Return failed-job flag if observable from current store."""


DependencyT = TypeVar("DependencyT")


def create_firestore_client() -> Any:
    settings = load_settings()
    try:
        from google.cloud import firestore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-cloud-firestore が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc

    project = settings.firestore_project_id or None
    return firestore.Client(project=project)


def create_watchlist_service() -> WatchlistService:
    client = create_firestore_client()
    repository = FirestoreWatchlistRepository(client)
    history_repository = FirestoreWatchlistHistoryRepository(client)
    return WatchlistService(repository, max_items=100, history_repository=history_repository)


def create_watchlist_history_repository() -> WatchlistHistoryReader:
    client = create_firestore_client()
    return FirestoreWatchlistHistoryRepository(client)


def create_notification_log_repository() -> NotificationLogReader:
    client = create_firestore_client()
    return FirestoreNotificationLogRepository(client)


def _resolve_dependency(
    request: Request,
    *,
    value_key: str,
    factory_key: str,
    missing_message: str,
) -> DependencyT:
    dependency = getattr(request.app.state, value_key, None)
    if dependency is not None:
        return dependency

    factory: Callable[[], DependencyT] | None = getattr(request.app.state, factory_key, None)
    if factory is None:
        raise RuntimeError(missing_message)
    dependency = factory()
    setattr(request.app.state, value_key, dependency)
    return dependency


def get_watchlist_service(request: Request) -> WatchlistService:
    return _resolve_dependency(
        request,
        value_key="watchlist_service",
        factory_key="watchlist_service_factory",
        missing_message="watchlist_service が初期化されていません。",
    )


def get_watchlist_history_repository(request: Request) -> WatchlistHistoryReader:
    return _resolve_dependency(
        request,
        value_key="watchlist_history_repository",
        factory_key="watchlist_history_repository_factory",
        missing_message="watchlist_history_repository が初期化されていません。",
    )


def get_notification_log_repository(request: Request) -> NotificationLogReader:
    return _resolve_dependency(
        request,
        value_key="notification_log_repository",
        factory_key="notification_log_repository_factory",
        missing_message="notification_log_repository が初期化されていません。",
    )

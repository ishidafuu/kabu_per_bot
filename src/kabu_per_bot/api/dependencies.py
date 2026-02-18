from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar

from fastapi import Request

from kabu_per_bot.admin_ops import (
    AdminOpsJob,
    AdminOpsSummary,
    BackfillRunRequest,
    CloudRunAdminOpsService,
    JobExecution,
)
from kabu_per_bot.api.errors import ForbiddenError, UnauthorizedError
from kabu_per_bot.earnings import EarningsCalendarEntry
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_daily_metrics_repository import FirestoreDailyMetricsRepository
from kabu_per_bot.storage.firestore_earnings_calendar_repository import FirestoreEarningsCalendarRepository
from kabu_per_bot.storage.firestore_metric_medians_repository import FirestoreMetricMediansRepository
from kabu_per_bot.storage.firestore_notification_log_repository import FirestoreNotificationLogRepository
from kabu_per_bot.storage.firestore_signal_state_repository import FirestoreSignalStateRepository
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

    def update_reason(self, *, record_id: str, reason: str | None) -> WatchlistHistoryRecord | None:
        """Update reason memo and return updated row."""


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
    ) -> bool:
        """Return failed-job flag."""


class DailyMetricsReader(Protocol):
    def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
        """Get recent metric rows."""

    def list_latest_by_tickers(self, tickers: list[str]) -> dict[str, DailyMetric]:
        """Get latest metric rows by ticker."""


class MetricMediansReader(Protocol):
    def list_recent(self, ticker: str, *, limit: int) -> list[MetricMedians]:
        """Get recent medians rows."""

    def list_latest_by_tickers(self, tickers: list[str]) -> dict[str, MetricMedians]:
        """Get latest medians rows by ticker."""


class SignalStateReader(Protocol):
    def get_latest(self, ticker: str):
        """Get latest signal state."""

    def get_latest_by_tickers(self, tickers: list[str]) -> dict[str, Any]:
        """Get latest signal states by ticker."""


class EarningsCalendarReader(Protocol):
    def list_by_ticker(self, ticker: str) -> list[EarningsCalendarEntry]:
        """List earnings calendar rows for ticker."""

    def list_next_by_tickers(self, tickers: list[str], *, from_date: str) -> dict[str, EarningsCalendarEntry]:
        """Get next earnings rows by ticker."""


class AdminOpsReader(Protocol):
    def list_jobs(self) -> tuple[AdminOpsJob, ...]:
        """List available admin jobs."""

    def list_executions(self, *, job_key: str, limit: int = 20) -> tuple[JobExecution, ...]:
        """List executions for a job key."""

    def run_job(self, *, job_key: str, backfill: BackfillRunRequest | None = None) -> JobExecution:
        """Run selected job and return latest execution."""

    def get_summary(self, *, limit_per_job: int = 5) -> AdminOpsSummary:
        """Get admin operation summary."""

    def send_discord_test(self, *, requested_uid: str) -> str:
        """Send Discord test notification."""


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


def create_daily_metrics_repository() -> DailyMetricsReader:
    client = create_firestore_client()
    return FirestoreDailyMetricsRepository(client)


def create_metric_medians_repository() -> MetricMediansReader:
    client = create_firestore_client()
    return FirestoreMetricMediansRepository(client)


def create_signal_state_repository() -> SignalStateReader:
    client = create_firestore_client()
    return FirestoreSignalStateRepository(client)


def create_earnings_calendar_repository() -> EarningsCalendarReader:
    client = create_firestore_client()
    return FirestoreEarningsCalendarRepository(client)


def create_admin_ops_service() -> AdminOpsReader:
    return CloudRunAdminOpsService()


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


def get_admin_ops_service(request: Request) -> AdminOpsReader:
    return _resolve_dependency(
        request,
        value_key="admin_ops_service",
        factory_key="admin_ops_service_factory",
        missing_message="admin_ops_service が初期化されていません。",
    )


def get_authenticated_uid(request: Request) -> str:
    uid = getattr(request.state, "auth_uid", None)
    if uid is None or not str(uid).strip():
        raise UnauthorizedError("認証情報が取得できません。")
    return str(uid).strip()


def require_admin_user(request: Request) -> None:
    if bool(getattr(request.state, "auth_is_admin", False)):
        return
    raise ForbiddenError("管理者権限が必要です。")

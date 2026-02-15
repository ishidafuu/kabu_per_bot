from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from kabu_per_bot.api.app import create_app
from kabu_per_bot.api.errors import ForbiddenError, UnauthorizedError
from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.storage.firestore_schema import normalize_ticker
from kabu_per_bot.watchlist import (
    CreateResult,
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchlistHistoryAction,
    WatchlistHistoryRecord,
    WatchlistItem,
    WatchlistService,
)

JST = ZoneInfo("Asia/Tokyo")


@dataclass
class InMemoryWatchlistRepository:
    docs: dict[str, WatchlistItem] = field(default_factory=dict)

    def try_create(self, item: WatchlistItem, *, max_items: int) -> CreateResult:
        if item.ticker in self.docs:
            return CreateResult.DUPLICATE
        if len(self.docs) >= max_items:
            return CreateResult.LIMIT_EXCEEDED
        self.docs[item.ticker] = item
        return CreateResult.CREATED

    def count(self) -> int:
        return len(self.docs)

    def get(self, ticker: str) -> WatchlistItem | None:
        return self.docs.get(normalize_ticker(ticker))

    def list_all(self) -> list[WatchlistItem]:
        return sorted(self.docs.values(), key=lambda item: item.ticker)

    def create(self, item: WatchlistItem) -> None:
        self.docs[item.ticker] = item

    def update(self, item: WatchlistItem) -> None:
        self.docs[item.ticker] = item

    def delete(self, ticker: str) -> bool:
        normalized = normalize_ticker(ticker)
        if normalized not in self.docs:
            return False
        del self.docs[normalized]
        return True


@dataclass
class FakeWatchlistHistoryRepository:
    rows: list[WatchlistHistoryRecord] = field(default_factory=list)

    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[WatchlistHistoryRecord]:
        values = list(self.rows)
        if ticker:
            normalized = normalize_ticker(ticker)
            values = [row for row in values if row.ticker == normalized]
        values.sort(key=lambda row: row.acted_at, reverse=True)
        if limit is None:
            return values[offset:]
        return values[offset : offset + limit]

    def count_timeline(self, *, ticker: str | None = None) -> int:
        if ticker is None:
            return len(self.rows)
        normalized = normalize_ticker(ticker)
        return sum(1 for row in self.rows if row.ticker == normalized)


@dataclass
class FakeNotificationLogRepository:
    rows: list[NotificationLogEntry] = field(default_factory=list)
    failed_job_rows: list[dict[str, str | int | bool]] = field(default_factory=list)

    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> list[NotificationLogEntry]:
        values = list(self.rows)
        if ticker:
            normalized = normalize_ticker(ticker)
            values = [row for row in values if row.ticker == normalized]
        if sent_at_from:
            from_dt = _parse_iso_datetime(sent_at_from)
            values = [row for row in values if _parse_iso_datetime(row.sent_at) >= from_dt]
        if sent_at_to:
            to_dt = _parse_iso_datetime(sent_at_to)
            values = [row for row in values if _parse_iso_datetime(row.sent_at) < to_dt]
        values.sort(key=lambda row: _parse_iso_datetime(row.sent_at), reverse=True)
        if limit is None:
            return values[offset:]
        return values[offset : offset + limit]

    def count_timeline(
        self,
        *,
        ticker: str | None = None,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> int:
        return len(
            self.list_timeline(
                ticker=ticker,
                sent_at_from=sent_at_from,
                sent_at_to=sent_at_to,
                limit=None,
                offset=0,
            )
        )

    def failed_job_exists(
        self,
        *,
        sent_at_from: str,
        sent_at_to: str,
    ) -> bool:
        from_dt = _parse_iso_datetime(sent_at_from)
        to_dt = _parse_iso_datetime(sent_at_to)
        for row in self.failed_job_rows:
            started_at_raw = row.get("started_at")
            if not isinstance(started_at_raw, str):
                continue
            started_at = _parse_iso_datetime(started_at_raw)
            if started_at < from_dt or started_at >= to_dt:
                continue
            job_name = str(row.get("job_name", "")).strip()
            if not job_name.startswith("earnings_"):
                continue
            status = str(row.get("status", "")).upper()
            if status == "FAILED":
                return True
            error_count = row.get("error_count")
            if isinstance(error_count, int) and error_count > 0:
                return True
        return False


class FakeTokenVerifier:
    def verify(self, token: str) -> dict[str, str]:
        if token == "valid-token":
            return {"uid": "user-1"}
        if token == "forbidden-token":
            raise ForbiddenError("権限がありません。")
        raise UnauthorizedError("認証に失敗しました。")


def _auth_header(token: str = "valid-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _watchlist_item(*, ticker: str, name: str) -> WatchlistItem:
    return WatchlistItem(
        ticker=normalize_ticker(ticker),
        name=name,
        metric_type=MetricType.PER,
        notify_channel=NotifyChannel.DISCORD,
        notify_timing=NotifyTiming.IMMEDIATE,
        ai_enabled=False,
        is_active=True,
        created_at="2026-02-12T00:00:00+09:00",
        updated_at="2026-02-12T00:00:00+09:00",
    )


def _jst_iso(*, day_offset: int = 0, hour: int = 9) -> str:
    value = datetime.now(JST).replace(hour=hour, minute=0, second=0, microsecond=0)
    value = value + timedelta(days=day_offset)
    return value.isoformat()


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _build_client(
    *,
    watchlist_items: list[WatchlistItem] | None = None,
    history_rows: list[WatchlistHistoryRecord] | None = None,
    notification_rows: list[NotificationLogEntry] | None = None,
    failed_job_rows: list[dict[str, str | int | bool]] | None = None,
) -> TestClient:
    repository = InMemoryWatchlistRepository()
    for item in watchlist_items or []:
        repository.docs[item.ticker] = item
    service = WatchlistService(repository, max_items=100)
    app = create_app(
        watchlist_service=service,
        watchlist_history_repository=FakeWatchlistHistoryRepository(history_rows or []),
        notification_log_repository=FakeNotificationLogRepository(
            notification_rows or [],
            failed_job_rows=failed_job_rows or [],
        ),
        token_verifier=FakeTokenVerifier(),
    )
    return TestClient(app)


class DashboardHistoryLogsApiTest(unittest.TestCase):
    def test_dashboard_requires_auth(self) -> None:
        client = _build_client()

        response = client.get("/api/v1/dashboard/summary")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "unauthorized")

    def test_history_and_logs_require_auth(self) -> None:
        client = _build_client()

        history_response = client.get("/api/v1/watchlist/history")
        self.assertEqual(history_response.status_code, 401)
        self.assertEqual(history_response.json()["error"]["code"], "unauthorized")

        logs_response = client.get("/api/v1/notifications/logs")
        self.assertEqual(logs_response.status_code, 401)
        self.assertEqual(logs_response.json()["error"]["code"], "unauthorized")

    def test_dashboard_summary_success(self) -> None:
        client = _build_client(
            watchlist_items=[
                _watchlist_item(ticker="3901:TSE", name="富士フイルム"),
                _watchlist_item(ticker="6758:TSE", name="ソニー"),
            ],
            notification_rows=[
                NotificationLogEntry(
                    entry_id="1",
                    ticker="3901:TSE",
                    category="PER割安",
                    condition_key="PER:1Y+3M",
                    sent_at=_jst_iso(hour=8),
                    channel="DISCORD",
                    payload_hash="h1",
                    is_strong=False,
                ),
                NotificationLogEntry(
                    entry_id="2",
                    ticker="6758:TSE",
                    category="超PSR割安",
                    condition_key="PSR:1Y+3M+1W",
                    sent_at=_jst_iso(hour=9),
                    channel="DISCORD",
                    payload_hash="h2",
                    is_strong=True,
                ),
                NotificationLogEntry(
                    entry_id="3",
                    ticker="6758:TSE",
                    category="データ不明",
                    condition_key="UNKNOWN:eps",
                    sent_at=_jst_iso(hour=10),
                    channel="DISCORD",
                    payload_hash="h3",
                    is_strong=False,
                ),
                NotificationLogEntry(
                    entry_id="4",
                    ticker="6758:TSE",
                    category="明日決算",
                    condition_key="EARNINGS:2026-02-13",
                    sent_at=_jst_iso(hour=11),
                    channel="DISCORD",
                    payload_hash="h4",
                    is_strong=False,
                ),
                NotificationLogEntry(
                    entry_id="5",
                    ticker="3901:TSE",
                    category="PER割安",
                    condition_key="PER:3M+1W",
                    sent_at=_jst_iso(day_offset=-1, hour=21),
                    channel="DISCORD",
                    payload_hash="h5",
                    is_strong=False,
                ),
            ],
        )

        response = client.get("/api/v1/dashboard/summary", headers=_auth_header())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["watchlist_count"], 2)
        self.assertEqual(body["today_notification_count"], 2)
        self.assertEqual(body["today_data_unknown_count"], 1)
        self.assertFalse(body["failed_job_exists"])

    def test_dashboard_summary_failed_job_flag(self) -> None:
        client = _build_client(
            watchlist_items=[_watchlist_item(ticker="3901:TSE", name="富士フイルム")],
            notification_rows=[],
            failed_job_rows=[
                {
                    "job_name": "earnings_weekly",
                    "started_at": _jst_iso(hour=3),
                    "status": "FAILED",
                    "error_count": 1,
                }
            ],
        )

        response = client.get("/api/v1/dashboard/summary", headers=_auth_header())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["failed_job_exists"])

    def test_dashboard_summary_failed_job_flag_is_jst_daily_window(self) -> None:
        client = _build_client(
            watchlist_items=[_watchlist_item(ticker="3901:TSE", name="富士フイルム")],
            notification_rows=[],
            failed_job_rows=[
                {
                    "job_name": "earnings_weekly",
                    "started_at": _jst_iso(day_offset=-1, hour=23),
                    "status": "FAILED",
                    "error_count": 1,
                }
            ],
        )

        response = client.get("/api/v1/dashboard/summary", headers=_auth_header())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["failed_job_exists"])

    def test_dashboard_summary_ignores_non_earnings_failed_job(self) -> None:
        client = _build_client(
            watchlist_items=[_watchlist_item(ticker="3901:TSE", name="富士フイルム")],
            notification_rows=[],
            failed_job_rows=[
                {
                    "job_name": "daily_pipeline",
                    "started_at": _jst_iso(hour=3),
                    "status": "FAILED",
                    "error_count": 1,
                }
            ],
        )

        response = client.get("/api/v1/dashboard/summary", headers=_auth_header())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["failed_job_exists"])

    def test_watchlist_history_timeline_order(self) -> None:
        client = _build_client(
            history_rows=[
                WatchlistHistoryRecord.create(
                    ticker="3901:TSE",
                    action=WatchlistHistoryAction.ADD,
                    reason="初回登録",
                    acted_at="2026-02-12T01:00:00+09:00",
                ),
                WatchlistHistoryRecord.create(
                    ticker="3901:TSE",
                    action=WatchlistHistoryAction.REMOVE,
                    reason="監視終了",
                    acted_at="2026-02-12T03:00:00+09:00",
                ),
                WatchlistHistoryRecord.create(
                    ticker="6758:TSE",
                    action=WatchlistHistoryAction.ADD,
                    reason=None,
                    acted_at="2026-02-12T02:00:00+09:00",
                ),
            ]
        )

        response = client.get(
            "/api/v1/watchlist/history?ticker=3901:TSE&limit=2&offset=0",
            headers=_auth_header(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["items"][0]["action"], "REMOVE")
        self.assertEqual(body["items"][1]["action"], "ADD")

    def test_notification_logs_timeline_order_and_paging(self) -> None:
        client = _build_client(
            notification_rows=[
                NotificationLogEntry(
                    entry_id="a",
                    ticker="3901:TSE",
                    category="PER割安",
                    condition_key="PER:1Y+3M",
                    sent_at="2026-02-12T09:00:00+09:00",
                    channel="DISCORD",
                    payload_hash="h1",
                    is_strong=False,
                ),
                NotificationLogEntry(
                    entry_id="b",
                    ticker="3901:TSE",
                    category="超PER割安",
                    condition_key="PER:1Y+3M+1W",
                    sent_at="2026-02-12T12:00:00+09:00",
                    channel="DISCORD",
                    payload_hash="h2",
                    is_strong=True,
                ),
                NotificationLogEntry(
                    entry_id="c",
                    ticker="3901:TSE",
                    category="データ不明",
                    condition_key="UNKNOWN:eps",
                    sent_at="2026-02-12T15:00:00+09:00",
                    channel="DISCORD",
                    payload_hash="h3",
                    is_strong=False,
                ),
            ]
        )

        response = client.get(
            "/api/v1/notifications/logs?ticker=3901:TSE&limit=1&offset=1",
            headers=_auth_header(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["entry_id"], "b")

    def test_validation_errors(self) -> None:
        client = _build_client()

        invalid_ticker = client.get("/api/v1/watchlist/history?ticker=invalid", headers=_auth_header())
        self.assertEqual(invalid_ticker.status_code, 422)
        self.assertEqual(invalid_ticker.json()["error"]["code"], "validation_error")

        invalid_limit = client.get("/api/v1/notifications/logs?limit=0", headers=_auth_header())
        self.assertEqual(invalid_limit.status_code, 422)
        self.assertEqual(invalid_limit.json()["error"]["code"], "validation_error")

    def test_uninitialized_repository_returns_internal_error(self) -> None:
        repository = InMemoryWatchlistRepository()
        service = WatchlistService(repository, max_items=100)
        app = create_app(watchlist_service=service, token_verifier=FakeTokenVerifier())
        app.state.notification_log_repository = None
        app.state.notification_log_repository_factory = None
        app.state.watchlist_history_repository = None
        app.state.watchlist_history_repository_factory = None
        client = TestClient(app, raise_server_exceptions=False)

        dashboard_response = client.get("/api/v1/dashboard/summary", headers=_auth_header())
        self.assertEqual(dashboard_response.status_code, 500)
        self.assertEqual(dashboard_response.json()["error"]["code"], "internal_error")

        history_response = client.get("/api/v1/watchlist/history", headers=_auth_header())
        self.assertEqual(history_response.status_code, 500)
        self.assertEqual(history_response.json()["error"]["code"], "internal_error")


if __name__ == "__main__":
    unittest.main()

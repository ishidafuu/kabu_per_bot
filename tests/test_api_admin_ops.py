from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from fastapi.testclient import TestClient

from kabu_per_bot.admin_ops import (
    AdminOpsConfigError,
    AdminOpsConflictError,
    AdminOpsJob,
    AdminOpsNotFoundError,
    AdminOpsSummary,
    BackfillRunRequest,
    JobExecution,
    SkipReasonCount,
    TickerScopedRunRequest,
)
from kabu_per_bot.api.app import create_app
from kabu_per_bot.api.errors import UnauthorizedError
from kabu_per_bot.technical import TechnicalIndicatorsDaily
from kabu_per_bot.watchlist import (
    CreateResult,
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchlistItem,
    WatchlistService,
)


class FakeTokenVerifier:
    def verify(self, token: str) -> dict[str, object]:
        if token == "admin-token":
            return {"uid": "admin-user", "admin": True}
        if token == "user-token":
            return {"uid": "normal-user"}
        raise UnauthorizedError("認証に失敗しました。")


@dataclass
class FakeNotificationLogRepository:
    deleted_entries: int = 0
    last_ticker: str | None = None

    def reset_grok_sns_cooldown(self, *, ticker: str | None = None) -> int:
        self.last_ticker = ticker
        return self.deleted_entries


@dataclass
class FakeIntelSeenRepository:
    deleted_entries: int = 0
    last_ticker: str | None = None

    def reset_sns_seen(self, *, ticker: str | None = None) -> int:
        self.last_ticker = ticker
        return self.deleted_entries


@dataclass
class FakeAdminOpsService:
    execution: JobExecution = field(
        default_factory=lambda: JobExecution(
            job_key="daily",
            job_label="日次ジョブ（IMMEDIATE）",
            job_name="kabu-daily",
            execution_name="kabu-daily-abcde",
            status="RUNNING",
            create_time="2026-02-18T13:00:00+00:00",
            start_time="2026-02-18T13:00:05+00:00",
            completion_time=None,
            message="Started deployed execution.",
            log_uri="https://example.com/log",
            skip_reasons=(SkipReasonCount(reason="2時間クールダウン中", count=3),),
            skip_reason_error=None,
        )
    )
    raise_conflict: bool = False
    last_backfill: BackfillRunRequest | None = None
    last_ticker_scope: TickerScopedRunRequest | None = None
    discord_sent_at: str = "2026-02-18T13:05:00+00:00"
    summary_call_args: tuple[int, bool, bool] | None = None

    def list_jobs(self) -> tuple[AdminOpsJob, ...]:
        return (
            AdminOpsJob(key="daily", label="日次ジョブ（IMMEDIATE）", job_name="kabu-daily"),
            AdminOpsJob(key="backfill", label="バックフィルジョブ", job_name="kabu-backfill"),
            AdminOpsJob(key="technical_full_refresh", label="技術全件再同期ジョブ", job_name="kabu-technical-full-refresh"),
        )

    def list_executions(self, *, job_key: str, limit: int = 20) -> tuple[JobExecution, ...]:
        _ = limit
        if job_key not in {"daily", "backfill", "technical_full_refresh"}:
            raise AdminOpsNotFoundError("jobが見つかりません。")
        return (self.execution,)

    def run_job(
        self,
        *,
        job_key: str,
        backfill: BackfillRunRequest | None = None,
        ticker_scope: TickerScopedRunRequest | None = None,
    ) -> JobExecution:
        if self.raise_conflict:
            raise AdminOpsConflictError("実行中です。")
        if job_key not in {"daily", "backfill", "technical_full_refresh"}:
            raise AdminOpsNotFoundError("jobが見つかりません。")
        if job_key != "backfill" and backfill is not None:
            raise AdminOpsConfigError("backfill は backfill job のみ指定できます。")
        if ticker_scope is not None:
            self.last_ticker_scope = ticker_scope
        if job_key == "backfill":
            if backfill is None:
                raise AdminOpsConfigError("backfill payload が必要です。")
            self.last_backfill = backfill
        return self.execution

    def get_summary(
        self,
        *,
        limit_per_job: int = 5,
        include_recent_executions: bool = True,
        include_skip_reasons: bool = True,
    ) -> AdminOpsSummary:
        self.summary_call_args = (limit_per_job, include_recent_executions, include_skip_reasons)
        return AdminOpsSummary(
            jobs=self.list_jobs(),
            recent_executions=(self.execution,) if include_recent_executions else (),
            latest_skip_reasons=(self.execution,) if include_skip_reasons else (),
        )

    def send_discord_test(self, *, requested_uid: str) -> str:
        _ = requested_uid
        return self.discord_sent_at


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
        return self.docs.get(ticker)

    def list_all(self) -> list[WatchlistItem]:
        return sorted(self.docs.values(), key=lambda item: item.ticker)

    def create(self, item: WatchlistItem) -> None:
        self.docs[item.ticker] = item

    def update(self, item: WatchlistItem) -> None:
        self.docs[item.ticker] = item

    def delete(self, ticker: str) -> bool:
        if ticker not in self.docs:
            return False
        del self.docs[ticker]
        return True


@dataclass
class InMemoryTechnicalIndicatorsRepository:
    rows_by_ticker: dict[str, list[TechnicalIndicatorsDaily]] = field(default_factory=dict)

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalIndicatorsDaily]:
        return list(self.rows_by_ticker.get(ticker, []))[:limit]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class AdminOpsApiTest(unittest.TestCase):
    def _watchlist_service(self, *tickers: str) -> WatchlistService:
        repository = InMemoryWatchlistRepository()
        service = WatchlistService(repository)
        for ticker in tickers:
            service.add_item(
                ticker=ticker,
                name=f"{ticker} 銘柄",
                metric_type=MetricType.PER,
                notify_channel=NotifyChannel.DISCORD,
                notify_timing=NotifyTiming.IMMEDIATE,
            )
        return service

    def test_admin_ops_requires_admin_role(self) -> None:
        app = create_app(
            admin_ops_service=FakeAdminOpsService(),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.get("/api/v1/admin/ops/summary", headers=_auth_header("user-token"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "forbidden")

    def test_admin_ops_summary_success(self) -> None:
        app = create_app(
            admin_ops_service=FakeAdminOpsService(),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.get("/api/v1/admin/ops/summary", headers=_auth_header("admin-token"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["jobs"]), 3)
        self.assertEqual(body["recent_executions"][0]["execution_name"], "kabu-daily-abcde")
        self.assertEqual(body["latest_skip_reasons"][0]["skip_reasons"][0]["reason"], "2時間クールダウン中")

    def test_admin_ops_summary_can_skip_heavy_sections(self) -> None:
        service = FakeAdminOpsService()
        app = create_app(
            admin_ops_service=service,
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.get(
            "/api/v1/admin/ops/summary?limit_per_job=3&include_recent_executions=false&include_skip_reasons=false",
            headers=_auth_header("admin-token"),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["recent_executions"], [])
        self.assertEqual(body["latest_skip_reasons"], [])
        self.assertEqual(service.summary_call_args, (3, False, False))

    def test_admin_run_job_conflict_returns_409(self) -> None:
        app = create_app(
            admin_ops_service=FakeAdminOpsService(raise_conflict=True),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.post("/api/v1/admin/ops/jobs/daily/run", headers=_auth_header("admin-token"))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "conflict")

    def test_admin_run_backfill_payload(self) -> None:
        service = FakeAdminOpsService()
        app = create_app(
            admin_ops_service=service,
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.post(
            "/api/v1/admin/ops/jobs/backfill/run",
            headers=_auth_header("admin-token"),
            json={
                "from_date": "2025-02-01",
                "to_date": "2026-02-18",
                "tickers": ["3984:TSE", "6238:TSE"],
                "dry_run": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(service.last_backfill)
        self.assertEqual(service.last_backfill.from_date, "2025-02-01")
        self.assertEqual(service.last_backfill.to_date, "2026-02-18")
        self.assertEqual(service.last_backfill.tickers, ("3984:TSE", "6238:TSE"))
        self.assertTrue(service.last_backfill.dry_run)

    def test_run_missing_latest_technical_filters_only_uncomputed_tickers(self) -> None:
        service = FakeAdminOpsService(
            execution=JobExecution(
                job_key="technical_full_refresh",
                job_label="技術全件再同期ジョブ",
                job_name="kabu-technical-full-refresh",
                execution_name="kabu-technical-full-refresh-abcde",
                status="RUNNING",
                create_time="2026-03-08T12:00:00+00:00",
                start_time="2026-03-08T12:00:05+00:00",
                completion_time=None,
                message="Started deployed execution.",
                log_uri="https://example.com/log",
                skip_reasons=(),
                skip_reason_error=None,
            )
        )
        technical_repo = InMemoryTechnicalIndicatorsRepository(
            rows_by_ticker={
                "3901:TSE": [
                    TechnicalIndicatorsDaily(
                        ticker="3901:TSE",
                        trade_date="2026-03-07",
                        schema_version=1,
                        calculated_at="2026-03-08T00:00:00+00:00",
                        values={},
                    )
                ]
            }
        )
        app = create_app(
            watchlist_service=self._watchlist_service("3901:TSE", "6501:TSE", "9432:TSE"),
            technical_indicators_repository=technical_repo,
            admin_ops_service=service,
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.post(
            "/api/v1/admin/ops/technical/missing-latest/run",
            headers=_auth_header("admin-token"),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["started"])
        self.assertEqual(body["target_count"], 2)
        self.assertEqual(body["target_tickers"], ["6501:TSE", "9432:TSE"])
        self.assertEqual(body["execution"]["execution_name"], "kabu-technical-full-refresh-abcde")
        self.assertIsNotNone(service.last_ticker_scope)
        self.assertEqual(service.last_ticker_scope.tickers, ("6501:TSE", "9432:TSE"))

    def test_run_missing_latest_technical_returns_noop_when_all_computed(self) -> None:
        technical_repo = InMemoryTechnicalIndicatorsRepository(
            rows_by_ticker={
                "3901:TSE": [
                    TechnicalIndicatorsDaily(
                        ticker="3901:TSE",
                        trade_date="2026-03-07",
                        schema_version=1,
                        calculated_at="2026-03-08T00:00:00+00:00",
                        values={},
                    )
                ]
            }
        )
        service = FakeAdminOpsService()
        app = create_app(
            watchlist_service=self._watchlist_service("3901:TSE"),
            technical_indicators_repository=technical_repo,
            admin_ops_service=service,
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.post(
            "/api/v1/admin/ops/technical/missing-latest/run",
            headers=_auth_header("admin-token"),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["started"])
        self.assertEqual(body["target_count"], 0)
        self.assertEqual(body["target_tickers"], [])
        self.assertIsNone(body["execution"])
        self.assertEqual(body["message"], "未計算の最新テクニカルはありません。")
        self.assertIsNone(service.last_ticker_scope)

    def test_discord_test_endpoint(self) -> None:
        app = create_app(
            admin_ops_service=FakeAdminOpsService(),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.post("/api/v1/admin/ops/discord/test", headers=_auth_header("admin-token"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sent_at"], "2026-02-18T13:05:00+00:00")

    def test_reset_grok_cooldown_endpoint(self) -> None:
        notification_repo = FakeNotificationLogRepository(deleted_entries=7)
        intel_seen_repo = FakeIntelSeenRepository(deleted_entries=5)
        app = create_app(
            admin_ops_service=FakeAdminOpsService(),
            notification_log_repository=notification_repo,
            intel_seen_repository=intel_seen_repo,
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.post(
            "/api/v1/admin/ops/grok/cooldown/reset?ticker=6490:TSE",
            headers=_auth_header("admin-token"),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["deleted_entries"], 12)
        self.assertEqual(body["deleted_notification_logs"], 7)
        self.assertEqual(body["deleted_seen_entries"], 5)
        self.assertEqual(body["ticker"], "6490:TSE")
        self.assertEqual(notification_repo.last_ticker, "6490:TSE")
        self.assertEqual(intel_seen_repo.last_ticker, "6490:TSE")

    def test_reset_grok_cooldown_endpoint_rejects_invalid_ticker(self) -> None:
        app = create_app(
            admin_ops_service=FakeAdminOpsService(),
            notification_log_repository=FakeNotificationLogRepository(deleted_entries=0),
            intel_seen_repository=FakeIntelSeenRepository(deleted_entries=0),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.post(
            "/api/v1/admin/ops/grok/cooldown/reset?ticker=ABC",
            headers=_auth_header("admin-token"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "bad_request")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from kabu_per_bot.api.app import create_app
import kabu_per_bot.api.routes.watchlist as watchlist_route
from kabu_per_bot.api.errors import ForbiddenError, UnauthorizedError
from kabu_per_bot.earnings import EarningsCalendarEntry
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.signal import NotificationLogEntry, SignalState
from kabu_per_bot.ir_url_candidates import IrUrlCandidate, IrUrlSuggestionError
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings
from kabu_per_bot.technical import TechnicalAlertOperator, TechnicalAlertRule, TechnicalIndicatorsDaily
from kabu_per_bot.storage.firestore_schema import normalize_ticker
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchPriority
from kabu_per_bot.watchlist import CreateResult, WatchlistHistoryAction, WatchlistHistoryRecord, WatchlistItem, WatchlistService


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

    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        category: str | None = None,
        is_strong: bool | None = None,
        limit: int | None = 100,
        offset: int = 0,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> list[NotificationLogEntry]:
        values = list(self.rows)
        if ticker:
            normalized = normalize_ticker(ticker)
            values = [row for row in values if row.ticker == normalized]
        if category:
            values = [row for row in values if row.category == category]
        if is_strong is not None:
            values = [row for row in values if row.is_strong is is_strong]
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
        category: str | None = None,
        is_strong: bool | None = None,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> int:
        return len(
            self.list_timeline(
                ticker=ticker,
                category=category,
                is_strong=is_strong,
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
        _ = sent_at_from, sent_at_to
        return False

    def reset_grok_sns_cooldown(self, *, ticker: str | None = None) -> int:
        _ = ticker
        return 0


@dataclass
class FakeGlobalSettingsRepository:
    settings: GlobalRuntimeSettings = field(default_factory=GlobalRuntimeSettings)

    def get_global_settings(self) -> GlobalRuntimeSettings:
        return self.settings


@dataclass
class FakeTechnicalAlertRulesRepository:
    rows: list[TechnicalAlertRule] = field(default_factory=list)

    def get(self, ticker: str, rule_id: str) -> TechnicalAlertRule | None:
        normalized = normalize_ticker(ticker)
        for row in self.rows:
            if row.ticker == normalized and row.rule_id == rule_id:
                return row
        return None

    def upsert(self, rule: TechnicalAlertRule) -> None:
        self.rows = [
            row
            for row in self.rows
            if not (row.ticker == rule.ticker and row.rule_id == rule.rule_id)
        ]
        self.rows.append(rule)

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalAlertRule]:
        normalized = normalize_ticker(ticker)
        values = [row for row in self.rows if row.ticker == normalized]
        values.sort(key=lambda row: row.updated_at or row.created_at or "", reverse=True)
        return values[:limit]


@dataclass
class FakeTechnicalIndicatorsRepository:
    rows: list[TechnicalIndicatorsDaily] = field(default_factory=list)

    def get(self, ticker: str, trade_date: str) -> TechnicalIndicatorsDaily | None:
        normalized = normalize_ticker(ticker)
        for row in self.rows:
            if row.ticker == normalized and row.trade_date == trade_date:
                return row
        return None

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalIndicatorsDaily]:
        normalized = normalize_ticker(ticker)
        values = [row for row in self.rows if row.ticker == normalized]
        values.sort(key=lambda row: row.trade_date, reverse=True)
        return values[:limit]


class FakeTokenVerifier:
    def verify(self, token: str) -> dict[str, str]:
        if token == "valid-token":
            return {"uid": "user-1"}
        if token == "forbidden-token":
            raise ForbiddenError("権限がありません。")
        raise UnauthorizedError("認証に失敗しました。")


class StaticIrUrlCandidateService:
    def __init__(self, rows: list[IrUrlCandidate]) -> None:
        self._rows = rows
        self.calls: list[dict[str, str | int]] = []

    def suggest_candidates(self, *, ticker: str, company_name: str, max_candidates: int = 5) -> list[IrUrlCandidate]:
        self.calls.append(
            {
                "ticker": ticker,
                "company_name": company_name,
                "max_candidates": max_candidates,
            }
        )
        return self._rows[:max_candidates]


class FailingIrUrlCandidateService:
    def suggest_candidates(self, *, ticker: str, company_name: str, max_candidates: int = 5) -> list[IrUrlCandidate]:
        del ticker, company_name, max_candidates
        raise IrUrlSuggestionError("vertex failed")


def _auth_header(token: str = "valid-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _build_client(
    *,
    max_items: int = 100,
    ir_url_candidate_service=None,
    watchlist_history_repository=None,
    notification_log_repository=None,
    daily_metrics_repository=None,
    metric_medians_repository=None,
    signal_state_repository=None,
    earnings_calendar_repository=None,
    technical_alert_rules_repository=None,
    technical_indicators_repository=None,
) -> TestClient:
    repository = InMemoryWatchlistRepository()
    service = WatchlistService(repository, max_items=max_items)
    app = create_app(
        watchlist_service=service,
        watchlist_history_repository=watchlist_history_repository,
        notification_log_repository=notification_log_repository,
        daily_metrics_repository=daily_metrics_repository,
        metric_medians_repository=metric_medians_repository,
        signal_state_repository=signal_state_repository,
        earnings_calendar_repository=earnings_calendar_repository,
        technical_alert_rules_repository=technical_alert_rules_repository,
        technical_indicators_repository=technical_indicators_repository,
        ir_url_candidate_service=ir_url_candidate_service,
        token_verifier=FakeTokenVerifier(),
    )
    return TestClient(app)


class WatchlistApiTest(unittest.TestCase):
    def test_healthz(self) -> None:
        client = _build_client()
        response = client.get("/api/v1/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_watchlist_requires_auth(self) -> None:
        client = _build_client()
        response = client.get("/api/v1/watchlist")

        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertEqual(body["error"]["code"], "unauthorized")

    def test_watchlist_forbidden(self) -> None:
        client = _build_client()
        response = client.get("/api/v1/watchlist", headers=_auth_header("forbidden-token"))

        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body["error"]["code"], "forbidden")

    def test_watchlist_returns_internal_error_when_token_verifier_factory_missing(self) -> None:
        repository = InMemoryWatchlistRepository()
        service = WatchlistService(repository, max_items=100)
        app = create_app(watchlist_service=service, token_verifier=None)
        app.state.token_verifier_factory = None
        client = TestClient(app)

        response = client.get("/api/v1/watchlist", headers=_auth_header())

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"]["code"], "internal_error")
        self.assertIn("token_verifier", body["error"]["message"])

    def test_watchlist_returns_internal_error_when_token_verifier_factory_fails(self) -> None:
        repository = InMemoryWatchlistRepository()
        service = WatchlistService(repository, max_items=100)
        app = create_app(watchlist_service=service, token_verifier=None)

        def _failing_factory():
            raise RuntimeError("boom")

        app.state.token_verifier_factory = _failing_factory
        client = TestClient(app)

        response = client.get("/api/v1/watchlist", headers=_auth_header())

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"]["code"], "internal_error")
        self.assertIn("token_verifier", body["error"]["message"])

    def test_watchlist_crud_and_search(self) -> None:
        client = _build_client()

        create_1 = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:tse",
                "name": "富士フイルム",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
                "always_notify_enabled": True,
            },
        )
        self.assertEqual(create_1.status_code, 201)
        self.assertTrue(create_1.json()["always_notify_enabled"])
        self.assertEqual(create_1.json()["ticker"], "3901:TSE")
        self.assertEqual(create_1.json()["priority"], "MEDIUM")
        self.assertFalse(create_1.json()["evaluation_enabled"])
        self.assertEqual(create_1.json()["evaluation_notify_mode"], "ALERT_ONLY")
        self.assertEqual(create_1.json()["evaluation_top_n"], 3)
        self.assertEqual(create_1.json()["evaluation_min_strength"], 4)

        create_2 = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "6758:TSE",
                "name": "ソニー",
                "metric_type": "PSR",
                "notify_channel": "DISCORD",
                "notify_timing": "AT_21",
                "always_notify_enabled": False,
            },
        )
        self.assertEqual(create_2.status_code, 201)

        list_response = client.get("/api/v1/watchlist?limit=1&offset=0", headers=_auth_header())
        self.assertEqual(list_response.status_code, 200)
        list_body = list_response.json()
        self.assertEqual(list_body["total"], 2)
        self.assertEqual(len(list_body["items"]), 1)

        search_response = client.get("/api/v1/watchlist?q=富士", headers=_auth_header())
        self.assertEqual(search_response.status_code, 200)
        self.assertEqual(search_response.json()["total"], 1)

        detail = client.get("/api/v1/watchlist/3901:tse", headers=_auth_header())
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["ticker"], "3901:TSE")

        update = client.patch(
            "/api/v1/watchlist/3901:TSE",
            headers=_auth_header(),
            json={
                "always_notify_enabled": False,
                "is_active": False,
                "priority": "HIGH",
                "evaluation_enabled": True,
                "evaluation_notify_mode": "ALERT_ONLY",
                "evaluation_top_n": 5,
                "evaluation_min_strength": 5,
            },
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()["notify_channel"], "DISCORD")
        self.assertFalse(update.json()["always_notify_enabled"])
        self.assertEqual(update.json()["is_active"], False)
        self.assertEqual(update.json()["priority"], "HIGH")
        self.assertTrue(update.json()["evaluation_enabled"])
        self.assertEqual(update.json()["evaluation_notify_mode"], "ALERT_ONLY")
        self.assertEqual(update.json()["evaluation_top_n"], 5)
        self.assertEqual(update.json()["evaluation_min_strength"], 5)

        delete = client.delete("/api/v1/watchlist/3901:TSE", headers=_auth_header())
        self.assertEqual(delete.status_code, 204)

        missing = client.get("/api/v1/watchlist/3901:TSE", headers=_auth_header())
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "not_found")

    def test_watchlist_supports_priority_filter(self) -> None:
        client = _build_client()
        payloads = [
            {
                "ticker": "3901:TSE",
                "name": "富士フイルム",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
                "priority": "HIGH",
            },
            {
                "ticker": "6758:TSE",
                "name": "ソニー",
                "metric_type": "PSR",
                "notify_channel": "DISCORD",
                "notify_timing": "AT_21",
                "priority": "LOW",
            },
        ]
        for payload in payloads:
            response = client.post("/api/v1/watchlist", headers=_auth_header(), json=payload)
            self.assertEqual(response.status_code, 201)

        filtered = client.get("/api/v1/watchlist?priority=HIGH", headers=_auth_header())

        self.assertEqual(filtered.status_code, 200)
        body = filtered.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["ticker"], "3901:TSE")
        self.assertEqual(body["items"][0]["priority"], "HIGH")

    def test_watchlist_detail_returns_summary_notifications_and_history(self) -> None:
        now = datetime.now(timezone.utc)
        recent_sent_at = now.isoformat()
        old_sent_at = (now - timedelta(days=40)).isoformat()
        history_at = (now - timedelta(days=1)).isoformat()

        class DailyRepo:
            def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
                _ = limit
                return [
                    DailyMetric(
                        ticker=ticker,
                        trade_date="2026-02-15",
                        close_price=1000,
                        eps_forecast=100,
                        sales_forecast=200,
                        per_value=10.0,
                        psr_value=5.0,
                        data_source="test",
                        fetched_at=now.isoformat(),
                    )
                ]

        class MedianRepo:
            def list_recent(self, ticker: str, *, limit: int) -> list[MetricMedians]:
                _ = limit
                return [
                    MetricMedians(
                        ticker=ticker,
                        trade_date="2026-02-15",
                        median_1w=11.0,
                        median_3m=12.0,
                        median_1y=13.0,
                        source_metric_type=MetricType.PER,
                        calculated_at=now.isoformat(),
                    )
                ]

        class SignalRepo:
            def get_latest(self, ticker: str) -> SignalState | None:
                return SignalState(
                    ticker=ticker,
                    trade_date="2026-02-15",
                    metric_type=MetricType.PER,
                    metric_value=10.0,
                    under_1w=True,
                    under_3m=True,
                    under_1y=True,
                    combo="1Y+3M+1W",
                    is_strong=True,
                    category="超PER割安",
                    streak_days=3,
                    updated_at=now.isoformat(),
                )

        class EarningsRepo:
            def list_by_ticker(self, ticker: str) -> list[EarningsCalendarEntry]:
                return [
                    EarningsCalendarEntry(
                        ticker=ticker,
                        earnings_date="2099-01-10",
                        earnings_time="15:00",
                        quarter="3Q",
                        source="test",
                        fetched_at=now.isoformat(),
                    )
                ]

        client = _build_client(
            watchlist_history_repository=FakeWatchlistHistoryRepository(
                rows=[
                    WatchlistHistoryRecord(
                        record_id="3901:TSE|ADD|1",
                        ticker="3901:TSE",
                        action=WatchlistHistoryAction.ADD,
                        reason="初回登録",
                        acted_at=history_at,
                    )
                ]
            ),
            notification_log_repository=FakeNotificationLogRepository(
                rows=[
                    NotificationLogEntry(
                        entry_id="log-1",
                        ticker="3901:TSE",
                        category="超PER割安",
                        condition_key="PER:1Y+3M+1W",
                        sent_at=recent_sent_at,
                        channel="DISCORD",
                        payload_hash="h1",
                        is_strong=True,
                        body="【超PER割安】3901:TSE 富士フイルム ...",
                    ),
                    NotificationLogEntry(
                        entry_id="log-2",
                        ticker="3901:TSE",
                        category="データ不明",
                        condition_key="UNKNOWN:eps",
                        sent_at=old_sent_at,
                        channel="DISCORD",
                        payload_hash="h2",
                        is_strong=False,
                        body="【データ不明】3901:TSE 富士フイルム 予想EPSが取得できませんでした",
                    ),
                ]
            ),
            daily_metrics_repository=DailyRepo(),
            metric_medians_repository=MedianRepo(),
            signal_state_repository=SignalRepo(),
            earnings_calendar_repository=EarningsRepo(),
        )
        create = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:TSE",
                "name": "富士フイルム",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )
        self.assertEqual(create.status_code, 201)

        response = client.get("/api/v1/watchlist/3901:TSE/detail", headers=_auth_header())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["item"]["ticker"], "3901:TSE")
        self.assertEqual(body["item"]["current_metric_value"], 10.0)
        self.assertEqual(body["summary"]["last_notification_category"], "超PER割安")
        self.assertEqual(body["summary"]["notification_count_7d"], 1)
        self.assertEqual(body["summary"]["strong_notification_count_30d"], 1)
        self.assertEqual(body["summary"]["data_unknown_count_30d"], 0)
        self.assertEqual(body["notifications"]["total"], 2)
        self.assertEqual(body["notifications"]["items"][0]["body"], "【超PER割安】3901:TSE 富士フイルム ...")
        self.assertEqual(body["history"]["total"], 1)
        self.assertEqual(body["history"]["items"][0]["reason"], "初回登録")
        self.assertEqual(body["technical_rules"]["total"], 0)
        self.assertIsNone(body["latest_technical"])
        self.assertEqual(body["technical_alert_history"]["total"], 0)

    def test_watchlist_detail_supports_notification_filters(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        client = _build_client(
            notification_log_repository=FakeNotificationLogRepository(
                rows=[
                    NotificationLogEntry(
                        entry_id="log-1",
                        ticker="3901:TSE",
                        category="超PER割安",
                        condition_key="PER:1Y+3M+1W",
                        sent_at=now,
                        channel="DISCORD",
                        payload_hash="h1",
                        is_strong=True,
                        body="strong",
                    ),
                    NotificationLogEntry(
                        entry_id="log-2",
                        ticker="3901:TSE",
                        category="データ不明",
                        condition_key="UNKNOWN:eps",
                        sent_at=now,
                        channel="DISCORD",
                        payload_hash="h2",
                        is_strong=False,
                        body="unknown",
                    ),
                ]
            ),
            watchlist_history_repository=FakeWatchlistHistoryRepository(),
        )
        create = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:TSE",
                "name": "富士フイルム",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )
        self.assertEqual(create.status_code, 201)

        response = client.get(
            "/api/v1/watchlist/3901:TSE/detail?category=超PER割安&strong_only=true",
            headers=_auth_header(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["notifications"]["total"], 1)
        self.assertEqual(body["notifications"]["items"][0]["entry_id"], "log-1")
        self.assertTrue(body["notifications"]["items"][0]["is_strong"])

    def test_suggest_ir_url_candidates_returns_validated_rows(self) -> None:
        candidate_service = StaticIrUrlCandidateService(
            [
                IrUrlCandidate(
                    url="https://example.com/ir/news",
                    title="IRニュース",
                    reason="IR一覧ページ",
                    confidence="High",
                    validation_status="VALID",
                    score=9,
                    http_status=200,
                    content_type="text/html",
                ),
                IrUrlCandidate(
                    url="https://example.com/contact",
                    title="お問い合わせ",
                    reason="関連ページ",
                    confidence="Low",
                    validation_status="WARNING",
                    score=2,
                    http_status=200,
                    content_type="text/html",
                ),
            ]
        )
        client = _build_client(ir_url_candidate_service=candidate_service)

        response = client.post(
            "/api/v1/watchlist/ir-url-candidates",
            headers=_auth_header(),
            json={
                "ticker": "3901:TSE",
                "company_name": "富士フイルム",
                "max_candidates": 2,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["items"][0]["url"], "https://example.com/ir/news")
        self.assertEqual(body["items"][0]["validation_status"], "VALID")
        self.assertEqual(candidate_service.calls[0]["ticker"], "3901:TSE")
        self.assertEqual(candidate_service.calls[0]["company_name"], "富士フイルム")
        self.assertEqual(candidate_service.calls[0]["max_candidates"], 2)

    def test_suggest_ir_url_candidates_returns_422_for_invalid_payload(self) -> None:
        client = _build_client(ir_url_candidate_service=StaticIrUrlCandidateService([]))

        response = client.post(
            "/api/v1/watchlist/ir-url-candidates",
            headers=_auth_header(),
            json={
                "ticker": "3901",
                "company_name": "",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_suggest_ir_url_candidates_returns_500_when_source_fails(self) -> None:
        client = _build_client(ir_url_candidate_service=FailingIrUrlCandidateService())

        response = client.post(
            "/api/v1/watchlist/ir-url-candidates",
            headers=_auth_header(),
            json={
                "ticker": "3901:TSE",
                "company_name": "富士フイルム",
            },
        )

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body["error"]["code"], "internal_error")
        self.assertIn("IR候補URLの生成に失敗しました", body["error"]["message"])

    def test_update_accepts_ai_enabled_only_for_backward_compatibility(self) -> None:
        client = _build_client()
        create = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:tse",
                "name": "富士フイルム",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )
        self.assertEqual(create.status_code, 201)

        update = client.patch(
            "/api/v1/watchlist/3901:TSE",
            headers=_auth_header(),
            json={"ai_enabled": False},
        )
        self.assertEqual(update.status_code, 200)
        # 現行運用ではai_enabledは常時有効として扱う。
        self.assertTrue(update.json()["ai_enabled"])

    def test_create_triggers_registration_warmup(self) -> None:
        client = _build_client()
        with patch("kabu_per_bot.api.routes.watchlist._run_watchlist_registration_warmup") as mocked_warmup:
            response = client.post(
                "/api/v1/watchlist",
                headers=_auth_header(),
                json={
                    "ticker": "3901:tse",
                    "name": "富士フイルム",
                    "metric_type": "PER",
                    "notify_channel": "DISCORD",
                    "notify_timing": "IMMEDIATE",
                },
            )
        self.assertEqual(response.status_code, 201)
        mocked_warmup.assert_called_once()

    def test_create_starts_warmup_in_background_thread(self) -> None:
        client = _build_client()
        with patch("kabu_per_bot.api.routes.watchlist._run_watchlist_registration_warmup_worker") as mocked_worker:
            with patch("kabu_per_bot.api.routes.watchlist.threading.Thread") as mocked_thread:
                mocked_thread.return_value.start.return_value = None
                response = client.post(
                    "/api/v1/watchlist",
                    headers=_auth_header(),
                    json={
                        "ticker": "3901:tse",
                        "name": "富士フイルム",
                        "metric_type": "PER",
                        "notify_channel": "DISCORD",
                        "notify_timing": "IMMEDIATE",
                    },
                )
        self.assertEqual(response.status_code, 201)
        mocked_thread.assert_called_once()
        mocked_thread.return_value.start.assert_called_once()
        mocked_worker.assert_not_called()

    def test_create_succeeds_when_warmup_thread_start_fails(self) -> None:
        client = _build_client()
        with patch("kabu_per_bot.api.routes.watchlist.threading.Thread") as mocked_thread:
            mocked_thread.return_value.start.side_effect = RuntimeError("can't start new thread")
            create_response = client.post(
                "/api/v1/watchlist",
                headers=_auth_header(),
                json={
                    "ticker": "3901:tse",
                    "name": "富士フイルム",
                    "metric_type": "PER",
                    "notify_channel": "DISCORD",
                    "notify_timing": "IMMEDIATE",
                },
            )
        self.assertEqual(create_response.status_code, 201)

        detail_response = client.get("/api/v1/watchlist/3901:TSE", headers=_auth_header())
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["ticker"], "3901:TSE")

    def test_registration_warmup_worker_skips_backfill_by_default(self) -> None:
        item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.dict(os.environ, {"WATCHLIST_REGISTRATION_BACKFILL_ENABLED": ""}, clear=False):
            with patch.object(
                watchlist_route,
                "_resolve_status_dependency_from_app",
                side_effect=[object(), object(), object()],
            ):
                with patch.object(watchlist_route, "upsert_latest_snapshot_metric"):
                    with patch.object(watchlist_route, "refresh_latest_medians_and_signal"):
                        with patch.object(watchlist_route, "_run_watchlist_registration_backfill_worker") as mocked_backfill:
                            watchlist_route._run_watchlist_registration_warmup_worker(
                                app=app,
                                item=item,
                                timezone_name="Asia/Tokyo",
                                window_1w_days=5,
                                window_3m_days=63,
                                window_1y_days=252,
                                api_key="dummy",
                            )
        mocked_backfill.assert_not_called()

    def test_registration_warmup_worker_runs_backfill_when_enabled(self) -> None:
        item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
        app = SimpleNamespace(state=SimpleNamespace())
        with patch.dict(os.environ, {"WATCHLIST_REGISTRATION_BACKFILL_ENABLED": "true"}, clear=False):
            with patch.object(
                watchlist_route,
                "_resolve_status_dependency_from_app",
                side_effect=[object(), object(), object()],
            ):
                with patch.object(watchlist_route, "upsert_latest_snapshot_metric"):
                    with patch.object(watchlist_route, "refresh_latest_medians_and_signal"):
                        with patch.object(watchlist_route, "_run_watchlist_registration_backfill_worker") as mocked_backfill:
                            watchlist_route._run_watchlist_registration_warmup_worker(
                                app=app,
                                item=item,
                                timezone_name="Asia/Tokyo",
                                window_1w_days=5,
                                window_3m_days=63,
                                window_1y_days=252,
                                api_key="dummy",
                            )
        mocked_backfill.assert_called_once()

    def test_duplicate_and_limit_error(self) -> None:
        client = _build_client(max_items=1)
        payload = {
            "ticker": "3901:TSE",
            "name": "富士フイルム",
            "metric_type": "PER",
            "notify_channel": "DISCORD",
            "notify_timing": "IMMEDIATE",
        }
        first = client.post("/api/v1/watchlist", headers=_auth_header(), json=payload)
        self.assertEqual(first.status_code, 201)

        duplicate = client.post("/api/v1/watchlist", headers=_auth_header(), json=payload)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "conflict")

        second = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "6758:TSE",
                "name": "ソニー",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json()["error"]["code"], "limit_exceeded")

    def test_validation_and_bad_request(self) -> None:
        client = _build_client()

        invalid_create = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "INVALID",
                "name": "A",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )
        self.assertEqual(invalid_create.status_code, 422)
        self.assertEqual(invalid_create.json()["error"]["code"], "validation_error")

        invalid_channel_create = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:TSE",
                "name": "A",
                "metric_type": "PER",
                "notify_channel": "OFF",
                "notify_timing": "IMMEDIATE",
            },
        )
        self.assertEqual(invalid_channel_create.status_code, 422)
        self.assertEqual(invalid_channel_create.json()["error"]["code"], "validation_error")

        empty_patch = client.patch("/api/v1/watchlist/3901:TSE", headers=_auth_header(), json={})
        self.assertEqual(empty_patch.status_code, 400)
        self.assertEqual(empty_patch.json()["error"]["code"], "bad_request")

        client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:TSE",
                "name": "A",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )
        invalid_channel_patch = client.patch(
            "/api/v1/watchlist/3901:TSE",
            headers=_auth_header(),
            json={"notify_channel": "OFF"},
        )
        self.assertEqual(invalid_channel_patch.status_code, 422)
        self.assertEqual(invalid_channel_patch.json()["error"]["code"], "validation_error")

        invalid_ticker = client.get("/api/v1/watchlist/not-a-ticker", headers=_auth_header())
        self.assertEqual(invalid_ticker.status_code, 422)
        self.assertEqual(invalid_ticker.json()["error"]["code"], "validation_error")

    def test_create_accepts_lowercase_market_and_normalizes_ticker(self) -> None:
        client = _build_client()
        response = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:tse",
                "name": "富士フイルム",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["ticker"], "3901:TSE")

    def test_openapi_and_docs(self) -> None:
        client = _build_client()
        docs = client.get("/docs")
        self.assertEqual(docs.status_code, 200)

        schema = client.get("/openapi.json")
        self.assertEqual(schema.status_code, 200)
        paths = schema.json()["paths"]
        self.assertIn("/api/v1/watchlist/{ticker}/detail", paths)
        self.assertIn("/api/v1/watchlist/{ticker}/technical-alert-rules", paths)
        post_responses = paths["/api/v1/watchlist"]["post"]["responses"]
        for status_code in ("401", "403", "409", "422", "429", "500"):
            self.assertIn(status_code, post_responses)

    def test_technical_alert_rule_crud(self) -> None:
        technical_repo = FakeTechnicalAlertRulesRepository()
        client = _build_client(technical_alert_rules_repository=technical_repo)

        client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:TSE",
                "name": "富士フイルム",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )

        create_response = client.post(
            "/api/v1/watchlist/3901:TSE/technical-alert-rules",
            headers=_auth_header(),
            json={
                "rule_name": "25日線上抜け",
                "field_key": "close_vs_ma25",
                "operator": "GTE",
                "threshold_value": 0,
                "note": "終値基準",
            },
        )
        self.assertEqual(create_response.status_code, 201)
        created = create_response.json()
        self.assertEqual(created["field_key"], "close_vs_ma25")
        self.assertEqual(created["operator"], "GTE")

        list_response = client.get(
            "/api/v1/watchlist/3901:TSE/technical-alert-rules",
            headers=_auth_header(),
        )
        self.assertEqual(list_response.status_code, 200)
        listed = list_response.json()
        self.assertEqual(listed["total"], 1)

        patch_response = client.patch(
            f"/api/v1/watchlist/3901:TSE/technical-alert-rules/{created['rule_id']}",
            headers=_auth_header(),
            json={"is_active": False},
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertFalse(patch_response.json()["is_active"])

    def test_technical_alert_rule_rejects_invalid_field_key(self) -> None:
        technical_repo = FakeTechnicalAlertRulesRepository()
        client = _build_client(technical_alert_rules_repository=technical_repo)

        client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:TSE",
                "name": "富士フイルム",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )

        response = client.post(
            "/api/v1/watchlist/3901:TSE/technical-alert-rules",
            headers=_auth_header(),
            json={
                "rule_name": "invalid",
                "field_key": "unknown_field",
                "operator": "GTE",
                "threshold_value": 0,
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_watchlist_detail_includes_technical_rules(self) -> None:
        technical_indicators_repo = FakeTechnicalIndicatorsRepository(
            rows=[
                TechnicalIndicatorsDaily(
                    ticker="3901:TSE",
                    trade_date="2026-03-08",
                    schema_version=1,
                    calculated_at="2026-03-08T00:00:00+00:00",
                    values={
                        "close_vs_ma25": 0.5,
                        "volume_ratio": 1.8,
                        "cross_up_ma25": True,
                    },
                )
            ]
        )
        technical_repo = FakeTechnicalAlertRulesRepository(
            rows=[
                TechnicalAlertRule.create(
                    ticker="3901:TSE",
                    rule_name="25日線上抜け",
                    field_key="close_vs_ma25",
                    operator=TechnicalAlertOperator.GTE,
                    threshold_value=0.0,
                    created_at="2026-03-08T00:00:00+00:00",
                    updated_at="2026-03-08T00:00:00+00:00",
                    rule_id="rule-1",
                )
            ]
        )
        client = _build_client(
            technical_alert_rules_repository=technical_repo,
            technical_indicators_repository=technical_indicators_repo,
            notification_log_repository=FakeNotificationLogRepository(),
            watchlist_history_repository=FakeWatchlistHistoryRepository(),
        )
        client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "3901:TSE",
                "name": "富士フイルム",
                "metric_type": "PER",
                "notify_channel": "DISCORD",
                "notify_timing": "IMMEDIATE",
            },
        )
        response = client.get("/api/v1/watchlist/3901:TSE/detail", headers=_auth_header())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["technical_rules"]["total"], 1)
        self.assertEqual(body["technical_rules"]["items"][0]["rule_id"], "rule-1")
        self.assertEqual(body["latest_technical"]["trade_date"], "2026-03-08")
        self.assertEqual(body["latest_technical"]["values"]["close_vs_ma25"], 0.5)

    def test_watchlist_list_include_status(self) -> None:
        repository = InMemoryWatchlistRepository()
        service = WatchlistService(repository, max_items=100)
        service.add_item(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type="PER",
            notify_channel="DISCORD",
            notify_timing="IMMEDIATE",
        )

        class DailyRepo:
            def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
                return [
                    DailyMetric(
                        ticker=ticker,
                        trade_date="2026-02-15",
                        close_price=1000,
                        eps_forecast=100,
                        sales_forecast=200,
                        per_value=10.0,
                        psr_value=5.0,
                        data_source="test",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                ]

        class MedianRepo:
            def list_recent(self, ticker: str, *, limit: int) -> list[MetricMedians]:
                return [
                    MetricMedians(
                        ticker=ticker,
                        trade_date="2026-02-15",
                        median_1w=11.0,
                        median_3m=12.0,
                        median_1y=13.0,
                        source_metric_type=MetricType.PER,
                        calculated_at=datetime.now(timezone.utc).isoformat(),
                    )
                ]

        class SignalRepo:
            def get_latest(self, ticker: str) -> SignalState | None:
                return SignalState(
                    ticker=ticker,
                    trade_date="2026-02-15",
                    metric_type=MetricType.PER,
                    metric_value=10.0,
                    under_1w=True,
                    under_3m=True,
                    under_1y=True,
                    combo="1Y+3M+1W",
                    is_strong=True,
                    category="超PER割安",
                    streak_days=3,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )

        class EarningsRepo:
            def list_by_ticker(self, ticker: str) -> list[EarningsCalendarEntry]:
                return [
                    EarningsCalendarEntry(
                        ticker=ticker,
                        earnings_date="2099-01-10",
                        earnings_time="15:00",
                        quarter="3Q",
                        source="test",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                ]

        app = create_app(
            watchlist_service=service,
            daily_metrics_repository=DailyRepo(),
            metric_medians_repository=MedianRepo(),
            signal_state_repository=SignalRepo(),
            earnings_calendar_repository=EarningsRepo(),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)
        response = client.get("/api/v1/watchlist?include_status=true", headers=_auth_header())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        item = body["items"][0]
        self.assertEqual(item["current_metric_value"], 10.0)
        self.assertEqual(item["median_1w"], 11.0)
        self.assertEqual(item["signal_category"], "超PER割安")
        self.assertIsNone(item["notification_skip_reason"])
        self.assertEqual(item["next_earnings_date"], "2099-01-10")
        self.assertEqual(item["priority"], WatchPriority.MEDIUM.value)
        self.assertIsInstance(item["next_earnings_days"], int)
        self.assertGreater(item["next_earnings_days"], 0)

    def test_watchlist_list_include_status_exposes_cooldown_skip_reason(self) -> None:
        repository = InMemoryWatchlistRepository()
        service = WatchlistService(repository, max_items=100)
        service.add_item(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type="PER",
            notify_channel="DISCORD",
            notify_timing="IMMEDIATE",
        )

        class DailyRepo:
            def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
                return [
                    DailyMetric(
                        ticker=ticker,
                        trade_date="2026-02-15",
                        close_price=1000,
                        eps_forecast=100,
                        sales_forecast=200,
                        per_value=10.0,
                        psr_value=5.0,
                        data_source="test",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                ]

        class MedianRepo:
            def list_recent(self, ticker: str, *, limit: int) -> list[MetricMedians]:
                return [
                    MetricMedians(
                        ticker=ticker,
                        trade_date="2026-02-15",
                        median_1w=11.0,
                        median_3m=12.0,
                        median_1y=13.0,
                        source_metric_type=MetricType.PER,
                        calculated_at=datetime.now(timezone.utc).isoformat(),
                    )
                ]

        class SignalRepo:
            def get_latest(self, ticker: str) -> SignalState | None:
                return SignalState(
                    ticker=ticker,
                    trade_date="2026-02-15",
                    metric_type=MetricType.PER,
                    metric_value=10.0,
                    under_1w=True,
                    under_3m=True,
                    under_1y=True,
                    combo="1Y+3M+1W",
                    is_strong=True,
                    category="超PER割安",
                    streak_days=1,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )

        class EarningsRepo:
            def list_by_ticker(self, ticker: str) -> list[EarningsCalendarEntry]:
                return [
                    EarningsCalendarEntry(
                        ticker=ticker,
                        earnings_date="2099-01-10",
                        earnings_time="15:00",
                        quarter="3Q",
                        source="test",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                ]

        now = datetime.now(timezone.utc)
        app = create_app(
            watchlist_service=service,
            daily_metrics_repository=DailyRepo(),
            metric_medians_repository=MedianRepo(),
            signal_state_repository=SignalRepo(),
            earnings_calendar_repository=EarningsRepo(),
            notification_log_repository=FakeNotificationLogRepository(
                rows=[
                    NotificationLogEntry(
                        entry_id="log-1",
                        ticker="3901:TSE",
                        category="超PER割安",
                        condition_key="PER:1Y+3M+1W",
                        sent_at=(now - timedelta(minutes=30)).isoformat(),
                        channel="DISCORD",
                        payload_hash="hash",
                        is_strong=True,
                    )
                ]
            ),
            global_settings_repository=FakeGlobalSettingsRepository(
                settings=GlobalRuntimeSettings(cooldown_hours=2)
            ),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)
        response = client.get("/api/v1/watchlist?include_status=true", headers=_auth_header())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["notification_skip_reason"], "2時間クールダウン中")

    def test_watchlist_list_include_status_ignores_stale_signal_state_for_skip_reason(self) -> None:
        repository = InMemoryWatchlistRepository()
        service = WatchlistService(repository, max_items=100)
        service.add_item(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type="PER",
            notify_channel="DISCORD",
            notify_timing="IMMEDIATE",
        )

        class DailyRepo:
            def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
                return [
                    DailyMetric(
                        ticker=ticker,
                        trade_date="2026-02-15",
                        close_price=1000,
                        eps_forecast=0,
                        sales_forecast=200,
                        per_value=None,
                        psr_value=5.0,
                        data_source="test",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                ]

        class MedianRepo:
            def list_recent(self, ticker: str, *, limit: int) -> list[MetricMedians]:
                return [
                    MetricMedians(
                        ticker=ticker,
                        trade_date="2026-02-15",
                        median_1w=11.0,
                        median_3m=12.0,
                        median_1y=13.0,
                        source_metric_type=MetricType.PER,
                        calculated_at=datetime.now(timezone.utc).isoformat(),
                    )
                ]

        class SignalRepo:
            def get_latest(self, ticker: str) -> SignalState | None:
                return SignalState(
                    ticker=ticker,
                    trade_date="2026-02-14",
                    metric_type=MetricType.PER,
                    metric_value=10.0,
                    under_1w=True,
                    under_3m=True,
                    under_1y=True,
                    combo="1Y+3M+1W",
                    is_strong=True,
                    category="超PER割安",
                    streak_days=3,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                )

        class EarningsRepo:
            def list_by_ticker(self, ticker: str) -> list[EarningsCalendarEntry]:
                return []

        app = create_app(
            watchlist_service=service,
            daily_metrics_repository=DailyRepo(),
            metric_medians_repository=MedianRepo(),
            signal_state_repository=SignalRepo(),
            earnings_calendar_repository=EarningsRepo(),
            notification_log_repository=FakeNotificationLogRepository(),
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)
        response = client.get("/api/v1/watchlist?include_status=true", headers=_auth_header())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["notification_skip_reason"], "データ不足（【データ不明】通知対象）")

    def test_watchlist_list_include_status_prefers_bulk_loaders(self) -> None:
        repository = InMemoryWatchlistRepository()
        service = WatchlistService(repository, max_items=100)
        service.add_item(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type="PER",
            notify_channel="DISCORD",
            notify_timing="IMMEDIATE",
        )
        service.add_item(
            ticker="6758:TSE",
            name="ソニー",
            metric_type="PSR",
            notify_channel="DISCORD",
            notify_timing="IMMEDIATE",
        )

        class BulkDailyRepo:
            single_calls = 0

            def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
                self.single_calls += 1
                return []

            def list_latest_by_tickers(self, tickers: list[str]) -> dict[str, DailyMetric]:
                return {
                    "3901:TSE": DailyMetric(
                        ticker="3901:TSE",
                        trade_date="2026-02-15",
                        close_price=1000,
                        eps_forecast=100,
                        sales_forecast=200,
                        per_value=10.0,
                        psr_value=5.0,
                        data_source="test",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    ),
                    "6758:TSE": DailyMetric(
                        ticker="6758:TSE",
                        trade_date="2026-02-15",
                        close_price=1500,
                        eps_forecast=100,
                        sales_forecast=100,
                        per_value=15.0,
                        psr_value=15.0,
                        data_source="test",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    ),
                }

        class BulkMedianRepo:
            single_calls = 0

            def list_recent(self, ticker: str, *, limit: int) -> list[MetricMedians]:
                self.single_calls += 1
                return []

            def list_latest_by_tickers(self, tickers: list[str]) -> dict[str, MetricMedians]:
                return {
                    ticker: MetricMedians(
                        ticker=ticker,
                        trade_date="2026-02-15",
                        median_1w=11.0,
                        median_3m=12.0,
                        median_1y=13.0,
                        source_metric_type=MetricType.PER,
                        calculated_at=datetime.now(timezone.utc).isoformat(),
                    )
                    for ticker in tickers
                }

        class BulkSignalRepo:
            single_calls = 0

            def get_latest(self, ticker: str) -> SignalState | None:
                self.single_calls += 1
                return None

            def get_latest_by_tickers(self, tickers: list[str]) -> dict[str, SignalState]:
                return {
                    "3901:TSE": SignalState(
                        ticker="3901:TSE",
                        trade_date="2026-02-15",
                        metric_type=MetricType.PER,
                        metric_value=10.0,
                        under_1w=True,
                        under_3m=True,
                        under_1y=True,
                        combo="1Y+3M+1W",
                        is_strong=True,
                        category="超PER割安",
                        streak_days=3,
                        updated_at=datetime.now(timezone.utc).isoformat(),
                    )
                }

        class BulkEarningsRepo:
            single_calls = 0

            def list_by_ticker(self, ticker: str) -> list[EarningsCalendarEntry]:
                self.single_calls += 1
                return []

            def list_next_by_tickers(self, tickers: list[str], *, from_date: str) -> dict[str, EarningsCalendarEntry]:
                return {
                    "3901:TSE": EarningsCalendarEntry(
                        ticker="3901:TSE",
                        earnings_date="2099-01-10",
                        earnings_time="15:00",
                        quarter="3Q",
                        source="test",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                    )
                }

        daily_repo = BulkDailyRepo()
        median_repo = BulkMedianRepo()
        signal_repo = BulkSignalRepo()
        earnings_repo = BulkEarningsRepo()

        app = create_app(
            watchlist_service=service,
            daily_metrics_repository=daily_repo,
            metric_medians_repository=median_repo,
            signal_state_repository=signal_repo,
            earnings_calendar_repository=earnings_repo,
            token_verifier=FakeTokenVerifier(),
        )
        client = TestClient(app)

        response = client.get("/api/v1/watchlist?include_status=true", headers=_auth_header())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(daily_repo.single_calls, 0)
        self.assertEqual(median_repo.single_calls, 0)
        self.assertEqual(signal_repo.single_calls, 0)
        self.assertEqual(earnings_repo.single_calls, 0)

    def test_watchlist_list_include_status_returns_error_when_dependency_is_missing(self) -> None:
        repository = InMemoryWatchlistRepository()
        service = WatchlistService(repository, max_items=100)
        service.add_item(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type="PER",
            notify_channel="DISCORD",
            notify_timing="IMMEDIATE",
        )
        app = create_app(
            watchlist_service=service,
            daily_metrics_repository=None,
            token_verifier=FakeTokenVerifier(),
        )
        app.state.daily_metrics_repository_factory = None
        client = TestClient(app)

        response = client.get("/api/v1/watchlist?include_status=true", headers=_auth_header())

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal_error")


if __name__ == "__main__":
    unittest.main()

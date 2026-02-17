from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import unittest

from fastapi.testclient import TestClient

from kabu_per_bot.api.app import create_app
from kabu_per_bot.api.errors import ForbiddenError, UnauthorizedError
from kabu_per_bot.earnings import EarningsCalendarEntry
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.signal import SignalState
from kabu_per_bot.watchlist import MetricType
from kabu_per_bot.watchlist import CreateResult, WatchlistItem, WatchlistService


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


class FakeTokenVerifier:
    def verify(self, token: str) -> dict[str, str]:
        if token == "valid-token":
            return {"uid": "user-1"}
        if token == "forbidden-token":
            raise ForbiddenError("権限がありません。")
        raise UnauthorizedError("認証に失敗しました。")


def _auth_header(token: str = "valid-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _build_client(*, max_items: int = 100) -> TestClient:
    repository = InMemoryWatchlistRepository()
    service = WatchlistService(repository, max_items=max_items)
    app = create_app(watchlist_service=service, token_verifier=FakeTokenVerifier())
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

    def test_watchlist_crud_and_search(self) -> None:
        client = _build_client()

        create_1 = client.post(
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
        self.assertEqual(create_1.status_code, 201)

        create_2 = client.post(
            "/api/v1/watchlist",
            headers=_auth_header(),
            json={
                "ticker": "6758:TSE",
                "name": "ソニー",
                "metric_type": "PSR",
                "notify_channel": "OFF",
                "notify_timing": "AT_21",
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
            json={"notify_channel": "OFF", "is_active": False},
        )
        self.assertEqual(update.status_code, 200)
        self.assertEqual(update.json()["notify_channel"], "OFF")
        self.assertEqual(update.json()["is_active"], False)

        delete = client.delete("/api/v1/watchlist/3901:TSE", headers=_auth_header())
        self.assertEqual(delete.status_code, 204)

        missing = client.get("/api/v1/watchlist/3901:TSE", headers=_auth_header())
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["error"]["code"], "not_found")

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

        empty_patch = client.patch("/api/v1/watchlist/3901:TSE", headers=_auth_header(), json={})
        self.assertEqual(empty_patch.status_code, 400)
        self.assertEqual(empty_patch.json()["error"]["code"], "bad_request")

        invalid_ticker = client.get("/api/v1/watchlist/not-a-ticker", headers=_auth_header())
        self.assertEqual(invalid_ticker.status_code, 422)
        self.assertEqual(invalid_ticker.json()["error"]["code"], "validation_error")

    def test_openapi_and_docs(self) -> None:
        client = _build_client()
        docs = client.get("/docs")
        self.assertEqual(docs.status_code, 200)

        schema = client.get("/openapi.json")
        self.assertEqual(schema.status_code, 200)
        paths = schema.json()["paths"]
        post_responses = paths["/api/v1/watchlist"]["post"]["responses"]
        for status_code in ("401", "403", "409", "422", "429", "500"):
            self.assertIn(status_code, post_responses)

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
        self.assertEqual(item["next_earnings_date"], "2099-01-10")

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

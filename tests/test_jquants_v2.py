from __future__ import annotations

import unittest

from kabu_per_bot.jquants_v2 import (
    JQuantsV2ApiError,
    JQuantsV2AuthError,
    JQuantsV2Client,
    normalize_jquants_code,
    normalize_jquants_date,
    ticker_to_jquants_code,
)


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict | None = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError("invalid json")
        return self._payload


class FakeHttpClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url: str, *, params: dict, headers: dict, timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout})
        if not self._responses:
            raise AssertionError("no fake response left")
        return self._responses.pop(0)

    def close(self) -> None:
        return None


class JQuantsV2ClientTest(unittest.TestCase):
    def test_ticker_to_code(self) -> None:
        self.assertEqual(ticker_to_jquants_code("3984:TSE"), "3984")
        self.assertEqual(normalize_jquants_code("3984"), "3984")
        self.assertEqual(normalize_jquants_code("39840"), "3984")

    def test_normalize_jquants_date(self) -> None:
        self.assertEqual(normalize_jquants_date("2026-02-18"), "2026-02-18")
        self.assertEqual(normalize_jquants_date("20260218"), "2026-02-18")

    def test_eq_bars_daily_pagination(self) -> None:
        fake_http = FakeHttpClient(
            [
                FakeResponse(
                    status_code=200,
                    payload={"data": [{"Date": "2026-02-17", "Code": "3984", "C": "100"}], "pagination_key": "NEXT"},
                ),
                FakeResponse(
                    status_code=200,
                    payload={"data": [{"Date": "2026-02-18", "Code": "3984", "C": "101"}]},
                ),
            ]
        )
        client = JQuantsV2Client(api_key="test-key", http_client=fake_http)
        rows = client.get_eq_bars_daily(code_or_ticker="3984:TSE", from_date="2026-02-17", to_date="2026-02-18")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["C"], "100")
        self.assertEqual(rows[1]["C"], "101")
        self.assertEqual(fake_http.calls[0]["params"]["code"], "3984")
        self.assertEqual(fake_http.calls[0]["params"]["from"], "2026-02-17")
        self.assertEqual(fake_http.calls[1]["params"]["pagination_key"], "NEXT")
        self.assertEqual(fake_http.calls[0]["headers"]["x-api-key"], "test-key")

    def test_auth_error_raises(self) -> None:
        fake_http = FakeHttpClient([FakeResponse(status_code=401, text="unauthorized")])
        client = JQuantsV2Client(api_key="bad-key", http_client=fake_http)
        with self.assertRaises(JQuantsV2AuthError):
            client.get_fin_summary(code_or_ticker="3984:TSE")

    def test_non_auth_error_raises(self) -> None:
        fake_http = FakeHttpClient([FakeResponse(status_code=500, text="internal error")])
        client = JQuantsV2Client(api_key="test-key", http_client=fake_http, retry_count=0)
        with self.assertRaises(JQuantsV2ApiError):
            client.get_fin_summary(code_or_ticker="3984:TSE")

    def test_retry_429_then_success(self) -> None:
        sleep_calls: list[float] = []
        fake_http = FakeHttpClient(
            [
                FakeResponse(status_code=429, text="rate limit"),
                FakeResponse(status_code=200, payload={"data": [{"DiscDate": "2026-02-18", "Code": "3984"}]}),
            ]
        )
        client = JQuantsV2Client(
            api_key="test-key",
            http_client=fake_http,
            retry_count=2,
            retry_base_sec=0.01,
            sleep_func=lambda sec: sleep_calls.append(sec),
        )
        rows = client.get_fin_summary(code_or_ticker="3984:TSE")
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(fake_http.calls), 2)
        self.assertEqual(len(sleep_calls), 1)

    def test_get_fin_summary_filters_by_period_and_lookback(self) -> None:
        fake_http = FakeHttpClient(
            [
                FakeResponse(
                    status_code=200,
                    payload={
                        "data": [
                            {"DiscDate": "2024-01-01", "Code": "3984"},
                            {"DiscDate": "2025-01-15", "Code": "3984"},
                            {"DiscDate": "2025-08-01", "Code": "3984"},
                        ]
                    },
                )
            ]
        )
        client = JQuantsV2Client(api_key="test-key", http_client=fake_http)
        rows = client.get_fin_summary(
            code_or_ticker="3984:TSE",
            from_date="2026-02-01",
            to_date="2026-02-18",
            lookback_days=400,
        )
        self.assertEqual([row["DiscDate"] for row in rows], ["2025-01-15", "2025-08-01"])

    def test_get_earnings_calendar(self) -> None:
        fake_http = FakeHttpClient(
            [
                FakeResponse(
                    status_code=200,
                    payload={
                        "data": [
                            {"Date": "2026-02-19", "Code": "39840"},
                        ]
                    },
                )
            ]
        )
        client = JQuantsV2Client(api_key="test-key", http_client=fake_http)
        rows = client.get_earnings_calendar()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Code"], "39840")
        self.assertEqual(fake_http.calls[0]["url"], "https://api.jquants.com/v2/equities/earnings-calendar")


if __name__ == "__main__":
    unittest.main()

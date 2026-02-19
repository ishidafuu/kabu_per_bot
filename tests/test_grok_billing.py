from __future__ import annotations

import unittest

from kabu_per_bot.grok_billing import fetch_prepaid_balance


class _FakeResponse:
    def __init__(self, *, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    def __init__(self, response: _FakeResponse | None = None, *, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float):
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


class GrokBillingTest(unittest.TestCase):
    def test_returns_not_configured_when_management_env_missing(self) -> None:
        result = fetch_prepaid_balance(api_key="", team_id="")

        self.assertFalse(result.configured)
        self.assertFalse(result.available)
        self.assertIsNone(result.amount)

    def test_parses_available_balance_amount(self) -> None:
        client = _FakeClient(
            _FakeResponse(
                status_code=200,
                payload={
                    "available_balance": {
                        "amount": "12.3456",
                        "currency": "usd",
                    }
                },
            )
        )

        result = fetch_prepaid_balance(
            api_key="mgmt-key",
            team_id="team-id",
            http_client=client,  # type: ignore[arg-type]
        )

        self.assertTrue(result.configured)
        self.assertTrue(result.available)
        self.assertEqual(result.amount, 12.3456)
        self.assertEqual(result.currency, "USD")
        self.assertEqual(len(client.calls), 1)

    def test_parses_fallback_amount_field(self) -> None:
        client = _FakeClient(
            _FakeResponse(
                status_code=200,
                payload={
                    "summary": {
                        "remaining_credits": 4.5,
                        "currency": "USD",
                    }
                },
            )
        )

        result = fetch_prepaid_balance(
            api_key="mgmt-key",
            team_id="team-id",
            http_client=client,  # type: ignore[arg-type]
        )

        self.assertTrue(result.available)
        self.assertEqual(result.amount, 4.5)
        self.assertEqual(result.currency, "USD")

    def test_parses_total_val_field(self) -> None:
        client = _FakeClient(
            _FakeResponse(
                status_code=200,
                payload={
                    "changes": [],
                    "total": {
                        "val": "-500",
                    },
                },
            )
        )

        result = fetch_prepaid_balance(
            api_key="mgmt-key",
            team_id="team-id",
            http_client=client,  # type: ignore[arg-type]
        )

        self.assertTrue(result.available)
        self.assertEqual(result.amount, -500.0)

    def test_returns_error_for_http_status_failure(self) -> None:
        client = _FakeClient(
            _FakeResponse(
                status_code=403,
                text='{"error":"no credits"}',
            )
        )

        result = fetch_prepaid_balance(
            api_key="mgmt-key",
            team_id="team-id",
            http_client=client,  # type: ignore[arg-type]
        )

        self.assertTrue(result.configured)
        self.assertFalse(result.available)
        self.assertIn("status=403", result.error or "")

    def test_returns_error_when_json_is_invalid(self) -> None:
        client = _FakeClient(
            _FakeResponse(
                status_code=200,
                payload=ValueError("invalid json"),
            )
        )

        result = fetch_prepaid_balance(
            api_key="mgmt-key",
            team_id="team-id",
            http_client=client,  # type: ignore[arg-type]
        )

        self.assertFalse(result.available)
        self.assertIn("解析に失敗", result.error or "")


if __name__ == "__main__":
    unittest.main()

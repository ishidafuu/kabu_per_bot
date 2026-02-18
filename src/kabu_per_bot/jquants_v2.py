from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from kabu_per_bot.storage.firestore_schema import normalize_ticker


JQUANTS_V2_BASE_URL = "https://api.jquants.com/v2"


class JQuantsV2Error(RuntimeError):
    """Base error for J-Quants v2 client."""


class JQuantsV2AuthError(JQuantsV2Error):
    """Raised when API key is invalid or missing permissions."""


class JQuantsV2ApiError(JQuantsV2Error):
    """Raised for non-auth API failures."""


def ticker_to_jquants_code(ticker: str) -> str:
    normalized_ticker = normalize_ticker(ticker)
    return normalized_ticker.split(":", 1)[0]


def normalize_jquants_code(code_or_ticker: str) -> str:
    value = code_or_ticker.strip().upper()
    if ":" in value:
        return ticker_to_jquants_code(value)
    if len(value) == 4 and value.isdigit():
        return value
    if len(value) == 5 and value.isdigit():
        return value[:4]
    raise ValueError(f"invalid code_or_ticker: {code_or_ticker}")


def normalize_jquants_date(value: str) -> str:
    raw = value.strip()
    if len(raw) == 10 and "-" in raw:
        return date.fromisoformat(raw).isoformat()
    if len(raw) == 8 and raw.isdigit():
        parsed = date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))
        return parsed.isoformat()
    raise ValueError(f"invalid date: {value}")


class JQuantsV2Client:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = JQUANTS_V2_BASE_URL,
        timeout_sec: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        api_key_value = api_key.strip()
        if not api_key_value:
            raise ValueError("api_key is required.")
        self._api_key = api_key_value
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.Client()

    def __del__(self) -> None:  # pragma: no cover
        if self._owns_client:
            try:
                self._http_client.close()
            except Exception:
                pass

    def get_eq_bars_daily(
        self,
        *,
        code_or_ticker: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        params = {
            "code": normalize_jquants_code(code_or_ticker),
            "from": normalize_jquants_date(from_date),
            "to": normalize_jquants_date(to_date),
        }
        return self._get_paginated(path="/equities/bars/daily", params=params)

    def get_fin_summary(
        self,
        *,
        code_or_ticker: str,
    ) -> list[dict[str, Any]]:
        params = {
            "code": normalize_jquants_code(code_or_ticker),
        }
        return self._get_paginated(path="/fins/summary", params=params)

    def _get_paginated(
        self,
        *,
        path: str,
        params: dict[str, Any],
        data_key: str = "data",
    ) -> list[dict[str, Any]]:
        url = f"{self._base_url}{path}"
        query = dict(params)
        rows: list[dict[str, Any]] = []

        while True:
            payload = self._get_json(url=url, params=query)
            batch = payload.get(data_key, [])
            if not isinstance(batch, list):
                raise JQuantsV2ApiError(f"unexpected response format: key={data_key}")
            rows.extend(batch)

            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                break
            query["pagination_key"] = pagination_key

        return rows

    def _get_json(self, *, url: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {"x-api-key": self._api_key}
        try:
            response = self._http_client.get(url, params=params, headers=headers, timeout=self._timeout_sec)
        except Exception as exc:
            raise JQuantsV2ApiError(f"http request failed: {exc}") from exc

        if response.status_code in {401, 403}:
            raise JQuantsV2AuthError(f"auth failed: status={response.status_code}")
        if response.status_code >= 400:
            preview = response.text[:200].replace("\n", " ")
            raise JQuantsV2ApiError(
                f"request failed: status={response.status_code} url={url} body={preview}"
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise JQuantsV2ApiError("response is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise JQuantsV2ApiError("response JSON root must be object.")
        return payload


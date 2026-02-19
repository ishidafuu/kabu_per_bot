from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(frozen=True)
class GrokPrepaidBalance:
    configured: bool
    available: bool
    amount: float | None = None
    currency: str | None = None
    fetched_at: str | None = None
    error: str | None = None


def fetch_prepaid_balance(
    *,
    api_key: str,
    team_id: str,
    base_url: str = "https://management-api.x.ai",
    timeout_sec: float = 8.0,
    http_client: httpx.Client | None = None,
) -> GrokPrepaidBalance:
    key = api_key.strip()
    team = team_id.strip()
    if not key or not team:
        return GrokPrepaidBalance(
            configured=False,
            available=False,
            error="GROK_MANAGEMENT_API_KEY または GROK_MANAGEMENT_TEAM_ID が未設定です。",
        )

    url = f"{base_url.rstrip('/')}/v1/billing/teams/{team}/prepaid/balance"
    owns_client = http_client is None
    client = http_client or httpx.Client()
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        response = client.get(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Accept": "application/json",
            },
            timeout=timeout_sec,
        )
    except Exception as exc:
        return GrokPrepaidBalance(
            configured=True,
            available=False,
            fetched_at=fetched_at,
            error=f"HTTPリクエストに失敗しました: {exc}",
        )
    finally:
        if owns_client:
            try:
                client.close()
            except Exception:
                pass

    if response.status_code >= 400:
        preview = response.text.replace("\n", " ").strip()[:200]
        return GrokPrepaidBalance(
            configured=True,
            available=False,
            fetched_at=fetched_at,
            error=f"status={response.status_code} body={preview}",
        )

    try:
        payload = response.json()
    except Exception as exc:
        return GrokPrepaidBalance(
            configured=True,
            available=False,
            fetched_at=fetched_at,
            error=f"レスポンスJSONの解析に失敗しました: {exc}",
        )

    amount, currency = _extract_amount_currency(payload)
    if amount is None:
        return GrokPrepaidBalance(
            configured=True,
            available=False,
            fetched_at=fetched_at,
            error="残高フィールドを特定できませんでした。",
        )
    return GrokPrepaidBalance(
        configured=True,
        available=True,
        amount=amount,
        currency=currency,
        fetched_at=fetched_at,
    )


def _extract_amount_currency(payload: Any) -> tuple[float | None, str | None]:
    candidates: tuple[tuple[str, ...], ...] = (
        ("available_balance", "amount"),
        ("available_balance", "value"),
        ("prepaid_balance", "amount"),
        ("prepaid_balance", "value"),
        ("remaining_balance", "amount"),
        ("remaining_balance", "value"),
        ("available_credits",),
        ("remaining_credits",),
        ("balance", "amount"),
        ("balance", "value"),
        ("balance",),
    )
    for path in candidates:
        value = _dig(payload, path)
        amount = _to_float(value)
        if amount is None:
            continue
        currency = _currency_from_parent(payload, path)
        return amount, currency

    fallback = _find_fallback_amount(payload)
    if fallback is None:
        return None, None
    amount, currency = fallback
    return amount, currency


def _dig(payload: Any, path: tuple[str, ...]) -> Any:
    node = payload
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _currency_from_parent(payload: Any, path: tuple[str, ...]) -> str | None:
    if len(path) >= 2:
        parent = _dig(payload, path[:-1])
        if isinstance(parent, dict):
            currency = str(parent.get("currency", "")).strip()
            if currency:
                return currency.upper()
    return _find_currency(payload)


def _find_currency(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("currency", "unit"):
            raw = payload.get(key)
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                return text.upper()
        for value in payload.values():
            found = _find_currency(value)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = _find_currency(value)
            if found:
                return found
    return None


def _find_fallback_amount(payload: Any) -> tuple[float, str | None] | None:
    best: tuple[int, float, str | None] | None = None
    if isinstance(payload, dict):
        for key, value in payload.items():
            amount = _to_float(value)
            if amount is not None:
                score = _amount_key_score(str(key))
                if score > 0:
                    candidate = (score, amount, _find_currency(payload))
                    if best is None or candidate[0] > best[0]:
                        best = candidate
            nested = _find_fallback_amount(value)
            if nested is not None:
                nested_score = 1
                if best is None or nested_score > best[0]:
                    best = (nested_score, nested[0], nested[1])
    elif isinstance(payload, list):
        for row in payload:
            nested = _find_fallback_amount(row)
            if nested is not None:
                nested_score = 1
                if best is None or nested_score > best[0]:
                    best = (nested_score, nested[0], nested[1])
    if best is None:
        return None
    return (best[1], best[2])


def _amount_key_score(key: str) -> int:
    lowered = key.strip().lower()
    if not lowered:
        return 0
    if "available" in lowered and ("balance" in lowered or "credit" in lowered):
        return 5
    if "remaining" in lowered and ("balance" in lowered or "credit" in lowered):
        return 5
    if "prepaid" in lowered and "balance" in lowered:
        return 4
    if lowered in {"balance", "amount", "value"}:
        return 2
    return 0

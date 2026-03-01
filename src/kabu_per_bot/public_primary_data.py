from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
import re

import httpx

from kabu_per_bot.storage.firestore_schema import normalize_ticker


class PublicPrimaryDataError(RuntimeError):
    """Base error for public primary data collection."""


class EdinetApiError(PublicPrimaryDataError):
    """Raised when EDINET API request/parse fails."""


class EStatApiError(PublicPrimaryDataError):
    """Raised when e-Stat API request/parse fails."""


@dataclass(frozen=True)
class EdinetFiling:
    doc_id: str
    sec_code: str
    ordinance_code: str
    form_code: str
    doc_description: str
    submitted_at: str
    api_document_url: str

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EStatMetricPoint:
    stats_data_id: str
    time_key: str
    value: float

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


class EdinetApiClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.edinet-fsa.go.jp/api/v2",
        timeout_sec: float = 20.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("api_key is required.")
        self._api_key = key
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._http_client = http_client or httpx.Client()
        self._owns_client = http_client is None
        self._daily_cache: dict[str, list[dict[str, Any]]] = {}

    def __del__(self) -> None:  # pragma: no cover - best effort
        if self._owns_client:
            try:
                self._http_client.close()
            except Exception:
                pass

    def collect_recent_filings(
        self,
        *,
        ticker: str,
        lookback_days: int = 120,
        max_items: int = 3,
        today: date | None = None,
    ) -> list[EdinetFiling]:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be > 0.")
        if max_items <= 0:
            raise ValueError("max_items must be > 0.")

        normalized_ticker = normalize_ticker(ticker)
        code4 = normalized_ticker.split(":", 1)[0]
        scan_from = today or datetime.now(timezone(timedelta(hours=9))).date()

        filings: list[EdinetFiling] = []
        seen_doc_ids: set[str] = set()
        for offset in range(lookback_days + 1):
            target_day = scan_from - timedelta(days=offset)
            rows = self._list_documents_for_date(target_day.isoformat())
            for row in rows:
                sec_code = str(row.get("secCode", "")).strip()
                if not sec_code.startswith(code4):
                    continue

                doc_description = str(row.get("docDescription", "")).strip()
                if not _is_supported_edinet_document(
                    ordinance_code=str(row.get("ordinanceCode", "")).strip(),
                    form_code=str(row.get("formCode", "")).strip(),
                    doc_description=doc_description,
                ):
                    continue

                doc_id = str(row.get("docID", "")).strip()
                if not doc_id or doc_id in seen_doc_ids:
                    continue
                seen_doc_ids.add(doc_id)

                submitted_at = _normalize_datetime(
                    raw=row.get("submitDateTime"),
                    fallback_day=target_day,
                )
                filings.append(
                    EdinetFiling(
                        doc_id=doc_id,
                        sec_code=sec_code,
                        ordinance_code=str(row.get("ordinanceCode", "")).strip(),
                        form_code=str(row.get("formCode", "")).strip(),
                        doc_description=doc_description or "提出書類",
                        submitted_at=submitted_at,
                        api_document_url=f"{self._base_url}/documents/{doc_id}",
                    )
                )

            if len(filings) >= max_items:
                break

        return sorted(filings, key=lambda row: row.submitted_at, reverse=True)[:max_items]

    def _list_documents_for_date(self, target_date: str) -> list[dict[str, Any]]:
        cached = self._daily_cache.get(target_date)
        if cached is not None:
            return cached

        try:
            response = self._http_client.get(
                f"{self._base_url}/documents.json",
                params={
                    "date": target_date,
                    "type": 2,
                },
                headers={
                    "Ocp-Apim-Subscription-Key": self._api_key,
                },
                timeout=self._timeout_sec,
            )
        except Exception as exc:
            raise EdinetApiError(f"EDINET documents API request failed: {exc}") from exc

        if int(getattr(response, "status_code", 0)) >= 400:
            raise EdinetApiError(
                f"EDINET documents API failed: status={response.status_code} date={target_date}"
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise EdinetApiError("EDINET documents API response is not valid JSON.") from exc

        rows = payload.get("results", [])
        if not isinstance(rows, list):
            raise EdinetApiError("EDINET documents API response format is invalid.")

        normalized_rows = [row for row in rows if isinstance(row, dict)]
        self._daily_cache[target_date] = normalized_rows
        return normalized_rows


class EStatApiClient:
    def __init__(
        self,
        *,
        app_id: str,
        base_url: str = "https://api.e-stat.go.jp/rest/3.0/app/json",
        timeout_sec: float = 20.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        normalized = app_id.strip()
        if not normalized:
            raise ValueError("app_id is required.")
        self._app_id = normalized
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._http_client = http_client or httpx.Client()
        self._owns_client = http_client is None
        self._latest_cache: dict[str, EStatMetricPoint | None] = {}

    def __del__(self) -> None:  # pragma: no cover - best effort
        if self._owns_client:
            try:
                self._http_client.close()
            except Exception:
                pass

    def fetch_latest_metric(self, *, stats_data_id: str) -> EStatMetricPoint | None:
        key = stats_data_id.strip()
        if not key:
            raise ValueError("stats_data_id is required.")
        if key in self._latest_cache:
            return self._latest_cache[key]

        try:
            response = self._http_client.get(
                f"{self._base_url}/getSimpleStatsData",
                params={
                    "appId": self._app_id,
                    "statsDataId": key,
                    "lang": "J",
                    "metaGetFlg": "Y",
                    "cntGetFlg": "N",
                    "limit": "200",
                },
                timeout=self._timeout_sec,
            )
        except Exception as exc:
            raise EStatApiError(f"e-Stat API request failed: {exc}") from exc

        if int(getattr(response, "status_code", 0)) >= 400:
            raise EStatApiError(f"e-Stat API failed: status={response.status_code} statsDataId={key}")
        try:
            payload = response.json()
        except Exception as exc:
            raise EStatApiError("e-Stat API response is not valid JSON.") from exc

        _assert_estat_success(payload=payload, stats_data_id=key)
        value_rows = _extract_estat_value_rows(payload)
        latest = _select_latest_estat_value(value_rows=value_rows, stats_data_id=key)
        self._latest_cache[key] = latest
        return latest


def _is_supported_edinet_document(
    *,
    ordinance_code: str,
    form_code: str,
    doc_description: str,
) -> bool:
    if ordinance_code == "010":
        return True
    if form_code in {"030000", "043000", "043001", "043002", "080000"}:
        return True
    normalized = doc_description.strip()
    keywords = (
        "有価証券報告書",
        "四半期報告書",
        "半期報告書",
        "臨時報告書",
        "内部統制報告書",
    )
    return any(keyword in normalized for keyword in keywords)


def _normalize_datetime(*, raw: Any, fallback_day: date) -> str:
    text = str(raw or "").strip()
    if not text:
        return datetime(
            year=fallback_day.year,
            month=fallback_day.month,
            day=fallback_day.day,
            tzinfo=timezone.utc,
        ).isoformat()
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime(
            year=fallback_day.year,
            month=fallback_day.month,
            day=fallback_day.day,
            tzinfo=timezone.utc,
        ).isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _extract_estat_value_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = payload.get("GET_STATS_DATA")
    if not isinstance(root, dict):
        raise EStatApiError("e-Stat API response missing GET_STATS_DATA.")
    stats = root.get("STATISTICAL_DATA")
    if not isinstance(stats, dict):
        raise EStatApiError("e-Stat API response missing STATISTICAL_DATA.")
    data_inf = stats.get("DATA_INF")
    if not isinstance(data_inf, dict):
        raise EStatApiError("e-Stat API response missing DATA_INF.")
    value = data_inf.get("VALUE")
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _assert_estat_success(*, payload: dict[str, Any], stats_data_id: str) -> None:
    root = payload.get("GET_STATS_DATA")
    if not isinstance(root, dict):
        raise EStatApiError("e-Stat API response missing GET_STATS_DATA.")
    result = root.get("RESULT")
    if not isinstance(result, dict):
        return
    status = str(result.get("STATUS", "")).strip()
    if status in {"", "0"}:
        return
    error_msg = str(result.get("ERROR_MSG", "")).strip() or "unknown error"
    raise EStatApiError(
        f"e-Stat API returned error status={status} statsDataId={stats_data_id} message={error_msg}"
    )


def _select_latest_estat_value(
    *,
    value_rows: list[dict[str, Any]],
    stats_data_id: str,
) -> EStatMetricPoint | None:
    points: list[EStatMetricPoint] = []
    for row in value_rows:
        time_key = str(row.get("@time", "")).strip()
        raw_value = str(row.get("$", "")).strip()
        if not time_key:
            continue
        numeric = _try_parse_float(raw_value)
        if numeric is None:
            continue
        points.append(
            EStatMetricPoint(
                stats_data_id=stats_data_id,
                time_key=time_key,
                value=numeric,
            )
        )
    if not points:
        return None
    return sorted(points, key=lambda row: _estat_time_sort_key(row.time_key), reverse=True)[0]


def _estat_time_sort_key(value: str) -> tuple[int, int]:
    month_match = re.fullmatch(r"(\d{4})M(\d{1,2})", value)
    if month_match:
        return (int(month_match.group(1)), int(month_match.group(2)))
    quarter_match = re.fullmatch(r"(\d{4})Q(\d)", value)
    if quarter_match:
        return (int(quarter_match.group(1)), int(quarter_match.group(2)) * 3)
    year_match = re.fullmatch(r"(\d{4})", value)
    if year_match:
        return (int(year_match.group(1)), 0)
    return (0, 0)


def _try_parse_float(raw: str) -> float | None:
    normalized = raw.strip().replace(",", "")
    if not normalized:
        return None
    if normalized in {"-", "--", "***", "..."}:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None

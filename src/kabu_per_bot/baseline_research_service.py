from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from kabu_per_bot.baseline_research import (
    BaselineCollectedData,
    BaselineCollectionError,
    BaselineRefreshFailure,
    BaselineRefreshResult,
    BaselineResearchCollector,
    BaselineResearchRepository,
    build_baseline_record,
)
from kabu_per_bot.market_data import MarketDataError, MarketDataSource
from kabu_per_bot.public_primary_data import (
    EStatApiClient,
    EStatApiError,
    EdinetApiClient,
    EdinetApiError,
    EdinetFiling,
)
from kabu_per_bot.watchlist import WatchlistItem


class Clock(Protocol):
    def now_iso(self) -> str:
        """Current UTC time in ISO8601."""


class UtcClock:
    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class DefaultBaselineResearchCollector:
    def __init__(
        self,
        market_data_source: MarketDataSource,
        *,
        edinet_client: EdinetApiClient | None = None,
        edinet_lookback_days: int = 120,
        estat_client: EStatApiClient | None = None,
        estat_cpi_stats_data_id: str = "",
    ) -> None:
        self._market_data_source = market_data_source
        self._edinet_client = edinet_client
        self._edinet_lookback_days = edinet_lookback_days
        self._estat_client = estat_client
        self._estat_cpi_stats_data_id = estat_cpi_stats_data_id.strip()

    def collect(self, *, ticker: str, company_name: str, as_of_month: str) -> BaselineCollectedData:
        try:
            snapshot = self._market_data_source.fetch_snapshot(ticker)
        except MarketDataError as exc:
            raise BaselineCollectionError(source="その他", reason=str(exc)) from exc

        source_label = _normalize_source(snapshot.source)
        raw = {
            "ticker": ticker,
            "company_name": company_name,
            "as_of_month": as_of_month,
            "snapshot": {
                "close_price": snapshot.close_price,
                "eps_forecast": snapshot.eps_forecast,
                "sales_forecast": snapshot.sales_forecast,
                "market_cap": snapshot.market_cap,
                "earnings_date": snapshot.earnings_date,
                "source": snapshot.source,
                "fetched_at": snapshot.fetched_at,
            },
        }
        structured = {
            "source_label": source_label,
            "close_price": snapshot.close_price,
            "eps_forecast": snapshot.eps_forecast,
            "sales_forecast": snapshot.sales_forecast,
            "earnings_date": snapshot.earnings_date,
        }
        summary = {
            "business_summary": f"{company_name}の主要事業と競争優位は月次更新で要確認",
            "growth_driver": "決算資料・IR更新で成長要因を再確認",
            "business_risk": "",
            "debt_comment": "有利子負債・自己資本比率は次回基礎調査で更新",
            "cf_comment": "営業CF/FCFは次回基礎調査で更新",
            "source_hint": source_label,
        }
        source_candidates = [source_label]
        enrichment_errors: list[str] = []

        if self._edinet_client is not None:
            try:
                filings = self._edinet_client.collect_recent_filings(
                    ticker=ticker,
                    lookback_days=self._edinet_lookback_days,
                    max_items=3,
                )
                raw["edinet"] = {
                    "lookback_days": self._edinet_lookback_days,
                    "filings": [row.to_document() for row in filings],
                }
                if filings:
                    latest = filings[0]
                    structured["edinet_latest_filing"] = {
                        "doc_id": latest.doc_id,
                        "form_code": latest.form_code,
                        "doc_description": latest.doc_description,
                        "submitted_at": latest.submitted_at,
                        "api_document_url": latest.api_document_url,
                    }
                    structured["edinet_recent_filing_count"] = len(filings)
                    summary["business_summary"] = _append_note(
                        summary["business_summary"],
                        f"直近開示: {latest.doc_description}（{latest.submitted_at[:10]}）",
                    )
                    summary["growth_driver"] = _append_note(
                        summary["growth_driver"],
                        f"EDINET一次情報を{len(filings)}件確認",
                    )
                    summary["business_risk"] = _append_note(
                        summary["business_risk"],
                        _infer_business_risk(filings),
                    )
                    source_candidates.append("決算短信/有報")
                else:
                    summary["business_risk"] = _append_note(
                        summary["business_risk"],
                        "EDINETで直近開示を確認できず、企業IRの補完確認が必要",
                    )
            except (EdinetApiError, Exception) as exc:
                enrichment_errors.append(f"edinet: {exc}")

        if self._estat_client is not None and self._estat_cpi_stats_data_id:
            try:
                macro_point = self._estat_client.fetch_latest_metric(
                    stats_data_id=self._estat_cpi_stats_data_id
                )
                if macro_point is not None:
                    raw["estat"] = {
                        "cpi": macro_point.to_document(),
                    }
                    structured["estat_cpi_latest"] = macro_point.to_document()
                    summary["macro_note"] = (
                        f"公的統計(CPI:{macro_point.stats_data_id}) "
                        f"{macro_point.time_key}={macro_point.value:.2f}"
                    )
                else:
                    raw["estat"] = {
                        "cpi": None,
                        "stats_data_id": self._estat_cpi_stats_data_id,
                        "missing_reason": "latest_value_not_found",
                    }
                    summary["macro_note"] = (
                        f"公的統計(CPI:{self._estat_cpi_stats_data_id})は最新値を取得できず"
                    )
            except (EStatApiError, Exception) as exc:
                enrichment_errors.append(f"estat: {exc}")
                summary["macro_note"] = (
                    f"公的統計(CPI:{self._estat_cpi_stats_data_id})取得失敗: {exc}"
                )

        if enrichment_errors:
            raw["enrichment_errors"] = list(enrichment_errors)

        primary_source = _choose_primary_source(source_candidates)
        reliability = _source_reliability_score(primary_source)
        return BaselineCollectedData(
            raw=raw,
            structured=structured,
            summary=summary,
            source=primary_source,
            reliability_score=reliability,
        )


def refresh_baseline_research(
    *,
    watchlist_items: list[WatchlistItem],
    collector: BaselineResearchCollector,
    repository: BaselineResearchRepository,
    as_of_month: str,
    clock: Clock | None = None,
) -> BaselineRefreshResult:
    utc_clock = clock or UtcClock()
    processed = 0
    updated = 0
    failed = 0
    failures: list[BaselineRefreshFailure] = []

    for item in watchlist_items:
        if not item.is_active or not item.evaluation_enabled:
            continue
        processed += 1
        previous = repository.get_latest(item.ticker)
        try:
            collected = collector.collect(
                ticker=item.ticker,
                company_name=item.name,
                as_of_month=as_of_month,
            )
            record = build_baseline_record(
                ticker=item.ticker,
                as_of_month=as_of_month,
                collected=collected,
                updated_at=utc_clock.now_iso(),
            )
            repository.upsert(record)
            updated += 1
        except BaselineCollectionError as exc:
            failed += 1
            failures.append(
                BaselineRefreshFailure(
                    ticker=item.ticker,
                    source=exc.source,
                    reason=exc.reason,
                    last_success_at=previous.updated_at if previous else None,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive
            failed += 1
            failures.append(
                BaselineRefreshFailure(
                    ticker=item.ticker,
                    source="その他",
                    reason=str(exc),
                    last_success_at=previous.updated_at if previous else None,
                )
            )

    return BaselineRefreshResult(
        processed_tickers=processed,
        updated_tickers=updated,
        failed_tickers=failed,
        failures=tuple(failures),
    )


def _normalize_source(source_name: str) -> str:
    normalized = source_name.strip()
    if normalized in {"四季報", "四季報online"}:
        return "四季報"
    if "IR" in normalized:
        return "企業IR"
    if normalized in {"決算短信", "有価証券報告書", "決算短信/有報"}:
        return "決算短信/有報"
    return "その他"


def _source_reliability_score(source_label: str) -> int:
    if source_label == "四季報":
        return 5
    if source_label == "企業IR":
        return 5
    if source_label == "決算短信/有報":
        return 4
    return 2


def _choose_primary_source(candidates: list[str]) -> str:
    if "四季報" in candidates:
        return "四季報"
    if "企業IR" in candidates:
        return "企業IR"
    if "決算短信/有報" in candidates:
        return "決算短信/有報"
    if candidates:
        return candidates[0]
    return "その他"


def _append_note(base: str, note: str) -> str:
    normalized_base = base.strip()
    normalized_note = note.strip()
    if not normalized_note:
        return normalized_base
    if not normalized_base:
        return normalized_note
    if normalized_note in normalized_base:
        return normalized_base
    return f"{normalized_base} / {normalized_note}"


def _infer_business_risk(filings: list[EdinetFiling]) -> str:
    latest = filings[0]
    description = latest.doc_description
    if "訂正" in description:
        return "訂正開示を含むため、前提の差分確認が必要"
    if "臨時報告書" in description:
        return "臨時報告書の内容確認を優先"
    return ""

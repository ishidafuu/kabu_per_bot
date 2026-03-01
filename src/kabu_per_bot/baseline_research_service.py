from __future__ import annotations

from dataclasses import dataclass
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
from kabu_per_bot.watchlist import WatchlistItem


class Clock(Protocol):
    def now_iso(self) -> str:
        """Current UTC time in ISO8601."""


class UtcClock:
    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class DefaultBaselineResearchCollector:
    def __init__(self, market_data_source: MarketDataSource) -> None:
        self._market_data_source = market_data_source

    def collect(self, *, ticker: str, company_name: str, as_of_month: str) -> BaselineCollectedData:
        try:
            snapshot = self._market_data_source.fetch_snapshot(ticker)
        except MarketDataError as exc:
            raise BaselineCollectionError(source="その他", reason=str(exc)) from exc

        source_label = _normalize_source(snapshot.source)
        reliability = _source_reliability_score(source_label)
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
            "debt_comment": "有利子負債・自己資本比率は次回基礎調査で更新",
            "cf_comment": "営業CF/FCFは次回基礎調査で更新",
            "source_hint": source_label,
        }
        return BaselineCollectedData(
            raw=raw,
            structured=structured,
            summary=summary,
            source=source_label,
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

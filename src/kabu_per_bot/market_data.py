from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from kabu_per_bot.storage.firestore_schema import normalize_ticker


class MarketDataError(RuntimeError):
    """Base error for market data fetching."""


class MarketDataFetchError(MarketDataError):
    def __init__(self, *, source: str, ticker: str, reason: str) -> None:
        self.source = source
        self.ticker = normalize_ticker(ticker)
        self.reason = reason.strip() or "unknown error"
        super().__init__(f"{source} failed for {self.ticker}: {self.reason}")


class MarketDataUnavailableError(MarketDataError):
    def __init__(self, *, ticker: str, reasons: list[str]) -> None:
        self.ticker = normalize_ticker(ticker)
        self.reasons = list(reasons)
        message = "; ".join(self.reasons) if self.reasons else "no sources configured"
        super().__init__(f"all market data sources failed for {self.ticker}: {message}")


@dataclass(frozen=True)
class MarketDataSnapshot:
    ticker: str
    close_price: float | None
    eps_forecast: float | None
    sales_forecast: float | None
    market_cap: float | None
    earnings_date: str | None
    source: str
    fetched_at: str

    @classmethod
    def create(
        cls,
        *,
        ticker: str,
        close_price: float | None,
        eps_forecast: float | None,
        sales_forecast: float | None,
        market_cap: float | None = None,
        earnings_date: str | None = None,
        source: str,
        fetched_at: str | None = None,
    ) -> "MarketDataSnapshot":
        return cls(
            ticker=normalize_ticker(ticker),
            close_price=close_price,
            eps_forecast=eps_forecast,
            sales_forecast=sales_forecast,
            market_cap=market_cap,
            earnings_date=earnings_date,
            source=source.strip(),
            fetched_at=fetched_at or datetime.now(timezone.utc).isoformat(),
        )

    def missing_fields(self) -> list[str]:
        fields: list[str] = []
        if self.close_price is None:
            fields.append("close_price")
        if self.eps_forecast is None:
            fields.append("eps_forecast")
        if self.sales_forecast is None:
            fields.append("sales_forecast")
        if not self.earnings_date:
            fields.append("earnings_date")
        return fields


class MarketDataSource(Protocol):
    @property
    def source_name(self) -> str:
        """Source name for logs."""

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        """Fetch market data snapshot."""


class FallbackMarketDataSource:
    def __init__(self, sources: list[MarketDataSource]) -> None:
        self._sources = list(sources)

    @property
    def source_name(self) -> str:
        return "fallback"

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        normalized_ticker = normalize_ticker(ticker)
        errors: list[str] = []
        if not self._sources:
            raise MarketDataUnavailableError(ticker=normalized_ticker, reasons=["source list is empty"])

        for source in self._sources:
            try:
                return source.fetch_snapshot(normalized_ticker)
            except MarketDataFetchError as exc:
                errors.append(str(exc))
            except Exception as exc:
                source_name = getattr(source, "source_name", source.__class__.__name__)
                errors.append(f"{source_name} failed for {normalized_ticker}: {exc}")
        raise MarketDataUnavailableError(ticker=normalized_ticker, reasons=errors)


class StubMarketDataSource:
    def __init__(self, source_name: str) -> None:
        self._source_name = source_name

    @property
    def source_name(self) -> str:
        return self._source_name

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        raise MarketDataFetchError(source=self._source_name, ticker=ticker, reason="not implemented")


class ShikihoMarketDataSource(StubMarketDataSource):
    def __init__(self) -> None:
        super().__init__("四季報online")


class KabutanMarketDataSource(StubMarketDataSource):
    def __init__(self) -> None:
        super().__init__("株探")


class YahooFinanceMarketDataSource(StubMarketDataSource):
    def __init__(self) -> None:
        super().__init__("Yahoo!ファイナンス")

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Any

from kabu_per_bot.market_data import MarketDataSnapshot
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date
from kabu_per_bot.watchlist import MetricType


@dataclass(frozen=True)
class DailyMetric:
    ticker: str
    trade_date: str
    close_price: float | None
    eps_forecast: float | None
    sales_forecast: float | None
    per_value: float | None
    psr_value: float | None
    data_source: str
    fetched_at: str

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "DailyMetric":
        return cls(
            ticker=normalize_ticker(str(data["ticker"])),
            trade_date=normalize_trade_date(str(data["trade_date"])),
            close_price=_as_float(data.get("close_price")),
            eps_forecast=_as_float(data.get("eps_forecast")),
            sales_forecast=_as_float(data.get("sales_forecast")),
            per_value=_as_float(data.get("per_value")),
            psr_value=_as_float(data.get("psr_value")),
            data_source=str(data.get("data_source", "")),
            fetched_at=str(data.get("fetched_at", "")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "close_price": self.close_price,
            "eps_forecast": self.eps_forecast,
            "sales_forecast": self.sales_forecast,
            "per_value": self.per_value,
            "psr_value": self.psr_value,
            "data_source": self.data_source,
            "fetched_at": self.fetched_at,
        }

    def missing_fields(self, *, metric_type: MetricType) -> list[str]:
        missing: list[str] = []
        if self.close_price is None:
            missing.append("close_price")
        if metric_type is MetricType.PER and (self.eps_forecast is None or self.eps_forecast <= 0):
            missing.append("eps_forecast")
        if metric_type is MetricType.PSR and (self.sales_forecast is None or self.sales_forecast <= 0):
            missing.append("sales_forecast")
        return missing


@dataclass(frozen=True)
class MetricMedians:
    ticker: str
    trade_date: str
    median_1w: float | None
    median_3m: float | None
    median_1y: float | None
    source_metric_type: MetricType
    calculated_at: str

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "MetricMedians":
        return cls(
            ticker=normalize_ticker(str(data["ticker"])),
            trade_date=normalize_trade_date(str(data["trade_date"])),
            median_1w=_as_float(data.get("median_1w")),
            median_3m=_as_float(data.get("median_3m")),
            median_1y=_as_float(data.get("median_1y")),
            source_metric_type=MetricType(str(data["source_metric_type"]).strip().upper()),
            calculated_at=str(data.get("calculated_at", "")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "median_1w": self.median_1w,
            "median_3m": self.median_3m,
            "median_1y": self.median_1y,
            "source_metric_type": self.source_metric_type.value,
            "calculated_at": self.calculated_at,
        }

    def insufficient_windows(self) -> list[str]:
        insufficient: list[str] = []
        if self.median_1w is None:
            insufficient.append("1W")
        if self.median_3m is None:
            insufficient.append("3M")
        if self.median_1y is None:
            insufficient.append("1Y")
        return insufficient


def build_daily_metric(
    *,
    ticker: str,
    trade_date: str,
    metric_type: MetricType,
    snapshot: MarketDataSnapshot,
) -> DailyMetric:
    normalized_ticker = normalize_ticker(ticker)
    normalized_trade_date = normalize_trade_date(trade_date)

    per_value: float | None = None
    psr_value: float | None = None

    if snapshot.close_price is not None:
        if snapshot.eps_forecast is not None and snapshot.eps_forecast > 0:
            per_value = snapshot.close_price / snapshot.eps_forecast
        if snapshot.sales_forecast is not None and snapshot.sales_forecast > 0:
            if snapshot.market_cap is not None and snapshot.market_cap > 0:
                psr_value = snapshot.market_cap / snapshot.sales_forecast
            else:
                psr_value = snapshot.close_price / snapshot.sales_forecast

    # metric_type is validated upstream, but we keep this guard to prevent silent mistakes.
    if metric_type not in {MetricType.PER, MetricType.PSR}:
        raise ValueError(f"unsupported metric_type: {metric_type}")

    return DailyMetric(
        ticker=normalized_ticker,
        trade_date=normalized_trade_date,
        close_price=snapshot.close_price,
        eps_forecast=snapshot.eps_forecast,
        sales_forecast=snapshot.sales_forecast,
        per_value=per_value,
        psr_value=psr_value,
        data_source=snapshot.source,
        fetched_at=snapshot.fetched_at,
    )


def calculate_metric_medians(
    *,
    ticker: str,
    trade_date: str,
    metric_type: MetricType,
    latest_first_metrics: list[DailyMetric],
    window_1w_days: int,
    window_3m_days: int,
    window_1y_days: int,
    calculated_at: str | None = None,
) -> MetricMedians:
    normalized_ticker = normalize_ticker(ticker)
    normalized_trade_date = normalize_trade_date(trade_date)
    if not (window_1w_days <= window_3m_days <= window_1y_days):
        raise ValueError("window order must satisfy 1W <= 3M <= 1Y.")

    values: list[float] = []
    for metric in latest_first_metrics:
        value = metric.per_value if metric_type is MetricType.PER else metric.psr_value
        if value is not None:
            values.append(value)

    return MetricMedians(
        ticker=normalized_ticker,
        trade_date=normalized_trade_date,
        median_1w=_window_median(values, window_1w_days),
        median_3m=_window_median(values, window_3m_days),
        median_1y=_window_median(values, window_1y_days),
        source_metric_type=metric_type,
        calculated_at=calculated_at or datetime.now(timezone.utc).isoformat(),
    )


def _window_median(values: list[float], window_size: int) -> float | None:
    if window_size <= 0:
        raise ValueError("window_size must be > 0.")
    if len(values) < window_size:
        return None
    return float(median(values[:window_size]))


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from kabu_per_bot.market_data import MarketDataSnapshot
from kabu_per_bot.metrics import DailyMetric, build_daily_metric
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date
from kabu_per_bot.watchlist import MetricType


JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class ForecastPoint:
    disclosed_at: datetime
    eps_forecast: float | None
    sales_forecast: float | None


def build_daily_metrics_from_jquants_v2(
    *,
    ticker: str,
    metric_type: MetricType,
    bars_daily_rows: list[dict[str, Any]],
    fin_summary_rows: list[dict[str, Any]],
    fetched_at: str,
) -> list[DailyMetric]:
    normalized_ticker = normalize_ticker(ticker)
    parsed_bars = _parse_bars(bars_daily_rows)
    forecast_points = _build_forecast_points(fin_summary_rows)

    rows: list[DailyMetric] = []
    next_forecast_index = 0
    eps_forecast: float | None = None
    sales_forecast: float | None = None

    for bar in parsed_bars:
        day_end = datetime.combine(bar.trade_date, time(hour=23, minute=59, second=59), tzinfo=JST)
        while next_forecast_index < len(forecast_points) and forecast_points[next_forecast_index].disclosed_at <= day_end:
            point = forecast_points[next_forecast_index]
            if point.eps_forecast is not None:
                eps_forecast = point.eps_forecast
            if point.sales_forecast is not None:
                sales_forecast = point.sales_forecast
            next_forecast_index += 1

        snapshot = MarketDataSnapshot.create(
            ticker=normalized_ticker,
            close_price=bar.close_price,
            eps_forecast=eps_forecast,
            sales_forecast=sales_forecast,
            source="J-Quants v2",
            earnings_date=None,
            fetched_at=fetched_at,
        )
        rows.append(
            build_daily_metric(
                ticker=normalized_ticker,
                trade_date=bar.trade_date.isoformat(),
                metric_type=metric_type,
                snapshot=snapshot,
            )
        )
    return rows


@dataclass(frozen=True)
class _ParsedBar:
    trade_date: date
    close_price: float | None


def _parse_bars(rows: list[dict[str, Any]]) -> list[_ParsedBar]:
    parsed: list[_ParsedBar] = []
    for row in rows:
        trade_date = _parse_trade_date(row.get("Date"))
        close_price = _as_float(row.get("C"))
        parsed.append(_ParsedBar(trade_date=trade_date, close_price=close_price))
    parsed.sort(key=lambda item: item.trade_date)
    return parsed


def _build_forecast_points(rows: list[dict[str, Any]]) -> list[ForecastPoint]:
    points: list[ForecastPoint] = []
    for row in rows:
        disclosed_at = _parse_disclosed_at(
            disclosed_date_raw=row.get("DiscDate"),
            disclosed_time_raw=row.get("DiscTime"),
        )
        points.append(
            ForecastPoint(
                disclosed_at=disclosed_at,
                eps_forecast=_as_float(row.get("FEPS")),
                sales_forecast=_as_float(row.get("FSales")),
            )
        )
    points.sort(key=lambda item: item.disclosed_at)
    return points


def _parse_trade_date(raw: Any) -> date:
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        raise ValueError("Date is required in bars row.")
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(normalize_trade_date(text))


def _parse_disclosed_at(*, disclosed_date_raw: Any, disclosed_time_raw: Any) -> datetime:
    disclosed_date = _parse_trade_date(disclosed_date_raw)
    disclosed_time = _parse_disclosed_time(disclosed_time_raw)
    return datetime.combine(disclosed_date, disclosed_time, tzinfo=JST)


def _parse_disclosed_time(raw: Any) -> time:
    text = str(raw or "").strip()
    if not text:
        return time(0, 0, 0)
    parts = text.split(":")
    if len(parts) == 2:
        hour = int(parts[0])
        minute = int(parts[1])
        return time(hour, minute, 0)
    if len(parts) == 3:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2])
        return time(hour, minute, second)
    raise ValueError(f"invalid DiscTime format: {text}")


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if text in {"-", "null", "None"}:
        return None
    return float(text.replace(",", ""))


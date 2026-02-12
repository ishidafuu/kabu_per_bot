from __future__ import annotations

from datetime import date
import hashlib
import re


SCHEMA_VERSION = 1
MIGRATION_ID = "0001_initial"

COLLECTION_WATCHLIST = "watchlist"
COLLECTION_WATCHLIST_HISTORY = "watchlist_history"
COLLECTION_DAILY_METRICS = "daily_metrics"
COLLECTION_METRIC_MEDIANS = "metric_medians"
COLLECTION_SIGNAL_STATE = "signal_state"
COLLECTION_EARNINGS_CALENDAR = "earnings_calendar"
COLLECTION_NOTIFICATION_LOG = "notification_log"

ALL_COLLECTIONS = (
    COLLECTION_WATCHLIST,
    COLLECTION_WATCHLIST_HISTORY,
    COLLECTION_DAILY_METRICS,
    COLLECTION_METRIC_MEDIANS,
    COLLECTION_SIGNAL_STATE,
    COLLECTION_EARNINGS_CALENDAR,
    COLLECTION_NOTIFICATION_LOG,
)

TICKER_PATTERN = re.compile(r"^\d{4}:[A-Z]+$")


def normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not TICKER_PATTERN.match(normalized):
        raise ValueError(f"Invalid ticker format: {ticker}")
    return normalized


def normalize_trade_date(trade_date: str) -> str:
    try:
        # Validate ISO date format strictly.
        parsed = date.fromisoformat(trade_date)
    except ValueError as exc:
        raise ValueError(f"Invalid date format: {trade_date}") from exc
    return parsed.isoformat()


def watchlist_doc_id(ticker: str) -> str:
    return normalize_ticker(ticker)


def daily_metrics_doc_id(ticker: str, trade_date: str) -> str:
    return f"{normalize_ticker(ticker)}|{normalize_trade_date(trade_date)}"


def metric_medians_doc_id(ticker: str, trade_date: str) -> str:
    return f"{normalize_ticker(ticker)}|{normalize_trade_date(trade_date)}"


def signal_state_doc_id(ticker: str, trade_date: str) -> str:
    return f"{normalize_ticker(ticker)}|{normalize_trade_date(trade_date)}"


def earnings_calendar_doc_id(
    ticker: str,
    earnings_date: str,
    quarter: str | None = None,
) -> str:
    normalized_quarter = (quarter or "NA").strip().upper()
    if not normalized_quarter:
        normalized_quarter = "NA"
    return (
        f"{normalize_ticker(ticker)}|"
        f"{normalize_trade_date(earnings_date)}|"
        f"{normalized_quarter}"
    )


def notification_condition_key(
    *,
    ticker: str,
    category: str,
    condition: str,
) -> str:
    raw = f"{normalize_ticker(ticker)}|{category.strip()}|{condition.strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


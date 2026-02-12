from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import logging
from typing import Any, Protocol

from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date

LOGGER = logging.getLogger(__name__)


class EarningsCalendarSyncError(RuntimeError):
    """Raised when earnings calendar sync fails."""


class EarningsCalendarSource(Protocol):
    def fetch_earnings_calendar(self, ticker: str) -> list[dict[str, Any] | "EarningsCalendarEntry"]:
        """Fetch earnings calendar rows for a single ticker."""


class EarningsCalendarRepository(Protocol):
    def replace_by_ticker(self, ticker: str, entries: list["EarningsCalendarEntry"]) -> None:
        """Replace earnings calendar rows for one ticker."""


@dataclass(frozen=True)
class EarningsCalendarEntry:
    ticker: str
    earnings_date: str
    earnings_time: str | None
    quarter: str | None
    source: str | None
    fetched_at: str | None

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "EarningsCalendarEntry":
        return cls(
            ticker=normalize_ticker(str(data["ticker"])),
            earnings_date=normalize_trade_date(str(data["earnings_date"])),
            earnings_time=_as_optional_text(data.get("earnings_time")),
            quarter=_as_optional_text(data.get("quarter")),
            source=_as_optional_text(data.get("source")),
            fetched_at=_as_optional_text(data.get("fetched_at")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "earnings_date": self.earnings_date,
            "earnings_time": self.earnings_time,
            "quarter": self.quarter,
            "source": self.source,
            "fetched_at": self.fetched_at,
        }


def sync_earnings_calendar_for_ticker(
    *,
    ticker: str,
    source: EarningsCalendarSource,
    repository: EarningsCalendarRepository,
    fetched_at: str | None = None,
) -> list[EarningsCalendarEntry]:
    normalized_ticker = normalize_ticker(ticker)
    source_name = _source_name_of(source)
    default_fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()

    try:
        raw_entries = source.fetch_earnings_calendar(normalized_ticker)
    except Exception as exc:
        LOGGER.exception("決算カレンダー取得失敗: ticker=%s source=%s", normalized_ticker, source_name)
        raise EarningsCalendarSyncError(
            f"決算カレンダー取得に失敗しました: ticker={normalized_ticker} source={source_name}"
        ) from exc
    if not isinstance(raw_entries, list):
        LOGGER.error(
            "決算カレンダー取得結果不正: ticker=%s source=%s type=%s",
            normalized_ticker,
            source_name,
            type(raw_entries).__name__,
        )
        raise EarningsCalendarSyncError(
            f"決算カレンダー取得結果が不正です: ticker={normalized_ticker} source={source_name}"
        )

    normalized_entries: list[EarningsCalendarEntry] = []
    for index, raw_entry in enumerate(raw_entries):
        try:
            entry = _normalize_entry(
                raw_entry=raw_entry,
                ticker=normalized_ticker,
                source_name=source_name,
                default_fetched_at=default_fetched_at,
            )
        except Exception as exc:
            LOGGER.error(
                "決算カレンダー変換失敗: ticker=%s source=%s index=%s error=%s",
                normalized_ticker,
                source_name,
                index,
                exc,
            )
            raise EarningsCalendarSyncError(
                f"決算カレンダー変換に失敗しました: ticker={normalized_ticker} source={source_name} index={index}"
            ) from exc

        normalized_entries.append(entry)

    try:
        repository.replace_by_ticker(normalized_ticker, normalized_entries)
    except Exception as exc:
        LOGGER.exception(
            "決算カレンダー保存失敗: ticker=%s source=%s rows=%s",
            normalized_ticker,
            source_name,
            len(normalized_entries),
        )
        raise EarningsCalendarSyncError(
            f"決算カレンダー保存に失敗しました: ticker={normalized_ticker} source={source_name}"
        ) from exc

    if not normalized_entries:
        LOGGER.warning("決算カレンダー0件: ticker=%s source=%s", normalized_ticker, source_name)

    return normalized_entries


def select_next_week_entries(entries: list[EarningsCalendarEntry], *, today: str) -> list[EarningsCalendarEntry]:
    today_date = date.fromisoformat(today)
    weekday = today_date.weekday()
    current_monday = today_date - timedelta(days=weekday)
    next_monday = current_monday + timedelta(days=7)
    next_sunday = next_monday + timedelta(days=6)
    selected = [
        entry
        for entry in entries
        if next_monday <= date.fromisoformat(entry.earnings_date) <= next_sunday
    ]
    return sorted(selected, key=lambda entry: (entry.earnings_date, entry.ticker))


def select_tomorrow_entries(entries: list[EarningsCalendarEntry], *, today: str) -> list[EarningsCalendarEntry]:
    tomorrow = date.fromisoformat(today) + timedelta(days=1)
    selected = [entry for entry in entries if date.fromisoformat(entry.earnings_date) == tomorrow]
    return sorted(selected, key=lambda entry: entry.ticker)


def _normalize_entry(
    *,
    raw_entry: dict[str, Any] | EarningsCalendarEntry,
    ticker: str,
    source_name: str,
    default_fetched_at: str,
) -> EarningsCalendarEntry:
    if isinstance(raw_entry, EarningsCalendarEntry):
        if normalize_ticker(raw_entry.ticker) != ticker:
            raise ValueError(f"ticker mismatch: {raw_entry.ticker} != {ticker}")
        return EarningsCalendarEntry(
            ticker=ticker,
            earnings_date=normalize_trade_date(raw_entry.earnings_date),
            earnings_time=_as_optional_text(raw_entry.earnings_time),
            quarter=_as_optional_text(raw_entry.quarter),
            source=_as_optional_text(raw_entry.source) or source_name,
            fetched_at=_as_optional_text(raw_entry.fetched_at) or default_fetched_at,
        )

    earnings_date = _as_optional_text(raw_entry.get("earnings_date"))
    if earnings_date is None:
        raise ValueError("earnings_date is required")

    entry_ticker = normalize_ticker(str(raw_entry.get("ticker", ticker)))
    if entry_ticker != ticker:
        raise ValueError(f"ticker mismatch: {entry_ticker} != {ticker}")

    return EarningsCalendarEntry(
        ticker=ticker,
        earnings_date=normalize_trade_date(earnings_date),
        earnings_time=_as_optional_text(raw_entry.get("earnings_time")),
        quarter=_as_optional_text(raw_entry.get("quarter")),
        source=_as_optional_text(raw_entry.get("source")) or source_name,
        fetched_at=_as_optional_text(raw_entry.get("fetched_at")) or default_fetched_at,
    )


def _as_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _source_name_of(source: EarningsCalendarSource) -> str:
    source_name = _as_optional_text(getattr(source, "source_name", None))
    if source_name is not None:
        return source_name
    return source.__class__.__name__

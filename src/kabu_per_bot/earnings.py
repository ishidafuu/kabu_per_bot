from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date


@dataclass(frozen=True)
class EarningsCalendarEntry:
    ticker: str
    earnings_date: str
    earnings_time: str | None
    quarter: str | None
    source: str
    fetched_at: str

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "EarningsCalendarEntry":
        return cls(
            ticker=normalize_ticker(str(data["ticker"])),
            earnings_date=normalize_trade_date(str(data["earnings_date"])),
            earnings_time=str(data["earnings_time"]) if data.get("earnings_time") else None,
            quarter=str(data["quarter"]) if data.get("quarter") else None,
            source=str(data.get("source", "")),
            fetched_at=str(data.get("fetched_at", "")),
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

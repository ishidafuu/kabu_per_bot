from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from kabu_per_bot.storage.firestore_schema import normalize_ticker


@dataclass(frozen=True)
class BaselineResearchRecord:
    ticker: str
    as_of_month: str
    raw: dict[str, Any]
    structured: dict[str, Any]
    summary: dict[str, Any]
    source: str
    reliability_score: int
    updated_at: str
    last_error: str | None = None

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "BaselineResearchRecord":
        return cls(
            ticker=normalize_ticker(str(data["ticker"])),
            as_of_month=str(data["as_of_month"]).strip(),
            raw=_as_dict(data.get("raw")),
            structured=_as_dict(data.get("structured")),
            summary=_as_dict(data.get("summary")),
            source=str(data.get("source", "other")).strip() or "other",
            reliability_score=_clamp_score(data.get("reliability_score", 1)),
            updated_at=_normalize_iso(data.get("updated_at")),
            last_error=_normalize_optional_text(data.get("last_error")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "as_of_month": self.as_of_month,
            "raw": dict(self.raw),
            "structured": dict(self.structured),
            "summary": dict(self.summary),
            "source": self.source,
            "reliability_score": _clamp_score(self.reliability_score),
            "updated_at": _normalize_iso(self.updated_at),
            "last_error": self.last_error,
        }


@dataclass(frozen=True)
class BaselineCollectedData:
    raw: dict[str, Any]
    structured: dict[str, Any]
    summary: dict[str, Any]
    source: str
    reliability_score: int


@dataclass(frozen=True)
class BaselineRefreshFailure:
    ticker: str
    source: str
    reason: str
    last_success_at: str | None


@dataclass(frozen=True)
class BaselineRefreshResult:
    processed_tickers: int
    updated_tickers: int
    failed_tickers: int
    failures: tuple[BaselineRefreshFailure, ...]


class BaselineResearchRepository(Protocol):
    def get_latest(self, ticker: str) -> BaselineResearchRecord | None:
        """Get latest baseline research row by ticker."""

    def upsert(self, record: BaselineResearchRecord) -> None:
        """Upsert baseline research row."""


class BaselineResearchCollector(Protocol):
    def collect(self, *, ticker: str, company_name: str, as_of_month: str) -> BaselineCollectedData:
        """Collect baseline research data."""


class BaselineCollectionError(RuntimeError):
    def __init__(self, *, source: str, reason: str) -> None:
        self.source = source.strip() or "unknown"
        self.reason = reason.strip() or "unknown error"
        super().__init__(f"{self.source}: {self.reason}")


def build_baseline_record(
    *,
    ticker: str,
    as_of_month: str,
    collected: BaselineCollectedData,
    updated_at: str | None = None,
    last_error: str | None = None,
) -> BaselineResearchRecord:
    return BaselineResearchRecord(
        ticker=normalize_ticker(ticker),
        as_of_month=as_of_month,
        raw=dict(collected.raw),
        structured=dict(collected.structured),
        summary=dict(collected.summary),
        source=collected.source,
        reliability_score=_clamp_score(collected.reliability_score),
        updated_at=updated_at or datetime.now(timezone.utc).isoformat(),
        last_error=_normalize_optional_text(last_error),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    raise ValueError("baseline field must be object")


def _normalize_iso(value: Any) -> str:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clamp_score(value: Any) -> int:
    parsed = int(value)
    if parsed < 1:
        return 1
    if parsed > 5:
        return 5
    return parsed

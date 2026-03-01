from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.baseline_research import (
    BaselineCollectedData,
    BaselineCollectionError,
    BaselineResearchRecord,
)
from kabu_per_bot.baseline_research_service import refresh_baseline_research
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchPriority, WatchlistItem


@dataclass
class FakeCollector:
    outputs: dict[str, BaselineCollectedData] = field(default_factory=dict)
    failures: dict[str, tuple[str, str]] = field(default_factory=dict)

    def collect(self, *, ticker: str, company_name: str, as_of_month: str) -> BaselineCollectedData:
        _ = company_name, as_of_month
        if ticker in self.failures:
            source, reason = self.failures[ticker]
            raise BaselineCollectionError(source=source, reason=reason)
        data = self.outputs.get(ticker)
        if data is None:
            raise BaselineCollectionError(source="その他", reason="missing fixture")
        return data


@dataclass
class FakeRepository:
    rows: dict[str, BaselineResearchRecord] = field(default_factory=dict)
    upsert_calls: list[BaselineResearchRecord] = field(default_factory=list)

    def get_latest(self, ticker: str) -> BaselineResearchRecord | None:
        return self.rows.get(ticker)

    def upsert(self, record: BaselineResearchRecord) -> None:
        self.rows[record.ticker] = record
        self.upsert_calls.append(record)


@dataclass
class FixedClock:
    now: str

    def now_iso(self) -> str:
        return self.now


def _watchlist_item(
    *,
    ticker: str,
    evaluation_enabled: bool,
    is_active: bool = True,
) -> WatchlistItem:
    return WatchlistItem(
        ticker=ticker,
        name=f"銘柄-{ticker}",
        metric_type=MetricType.PER,
        notify_channel=NotifyChannel.DISCORD,
        notify_timing=NotifyTiming.IMMEDIATE,
        priority=WatchPriority.MEDIUM,
        is_active=is_active,
        evaluation_enabled=evaluation_enabled,
    )


def _collected(*, source: str = "四季報", reliability_score: int = 5) -> BaselineCollectedData:
    return BaselineCollectedData(
        raw={"source": source},
        structured={"source_label": source},
        summary={"business_summary": "summary"},
        source=source,
        reliability_score=reliability_score,
    )


class BaselineResearchServiceTest(unittest.TestCase):
    def test_refresh_processes_only_active_and_enabled_watchlist(self) -> None:
        collector = FakeCollector(
            outputs={
                "3901:TSE": _collected(),
                "6758:TSE": _collected(source="企業IR"),
            }
        )
        repo = FakeRepository()
        items = [
            _watchlist_item(ticker="3901:TSE", evaluation_enabled=True, is_active=True),
            _watchlist_item(ticker="6758:TSE", evaluation_enabled=True, is_active=False),
            _watchlist_item(ticker="7203:TSE", evaluation_enabled=False, is_active=True),
        ]

        result = refresh_baseline_research(
            watchlist_items=items,
            collector=collector,
            repository=repo,
            as_of_month="2026-03",
            clock=FixedClock("2026-03-01T09:00:00+00:00"),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.updated_tickers, 1)
        self.assertEqual(result.failed_tickers, 0)
        self.assertEqual(len(result.failures), 0)
        self.assertEqual(len(repo.upsert_calls), 1)
        self.assertIn("3901:TSE", repo.rows)
        self.assertNotIn("6758:TSE", repo.rows)
        self.assertNotIn("7203:TSE", repo.rows)

    def test_refresh_keeps_previous_data_and_reports_failure(self) -> None:
        previous = BaselineResearchRecord(
            ticker="3901:TSE",
            as_of_month="2026-02",
            raw={"snapshot": "old"},
            structured={"source_label": "四季報"},
            summary={"business_summary": "old"},
            source="四季報",
            reliability_score=5,
            updated_at="2026-02-01T09:00:00+00:00",
        )
        repo = FakeRepository(rows={"3901:TSE": previous})
        collector = FakeCollector(
            failures={
                "3901:TSE": ("企業IR", "HTTP 429"),
            }
        )

        result = refresh_baseline_research(
            watchlist_items=[_watchlist_item(ticker="3901:TSE", evaluation_enabled=True)],
            collector=collector,
            repository=repo,
            as_of_month="2026-03",
            clock=FixedClock("2026-03-01T09:00:00+00:00"),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.updated_tickers, 0)
        self.assertEqual(result.failed_tickers, 1)
        self.assertEqual(len(result.failures), 1)
        failure = result.failures[0]
        self.assertEqual(failure.ticker, "3901:TSE")
        self.assertEqual(failure.source, "企業IR")
        self.assertEqual(failure.reason, "HTTP 429")
        self.assertEqual(failure.last_success_at, "2026-02-01T09:00:00+00:00")
        self.assertEqual(repo.rows["3901:TSE"], previous)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from kabu_per_bot.intelligence import (
    CompositeIntelSource,
    HeuristicAiAnalyzer,
    IntelEvent,
    IntelKind,
    IntelSourceError,
)
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


class IntelligenceTest(unittest.TestCase):
    def test_heuristic_ai_analyzer_returns_labels(self) -> None:
        analyzer = HeuristicAiAnalyzer()
        item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            ai_enabled=True,
        )
        event = IntelEvent(
            ticker="3901:TSE",
            kind=IntelKind.SNS,
            title="@fujifilm_ir",
            url="https://x.com/fujifilm_ir/status/1",
            published_at="2026-02-15T00:00:00+09:00",
            source_label="公式",
            content="新製品の受注が好調で増収見込み",
        )
        insight = analyzer.analyze(item=item, event=event)
        self.assertEqual(insight.sns_label, "公式")
        self.assertEqual(insight.tone, "ポジ")
        self.assertIn(event.url, insight.evidence_urls)

    def test_event_fingerprint_is_stable_when_only_published_at_changes(self) -> None:
        event_a = IntelEvent(
            ticker="3901:TSE",
            kind=IntelKind.IR,
            title="決算資料を公開",
            url="https://example.com/ir/1",
            published_at="2026-02-15T00:00:00+09:00",
            source_label="IRサイト",
            content="決算資料を公開しました",
        )
        event_b = IntelEvent(
            ticker="3901:TSE",
            kind=IntelKind.IR,
            title="決算資料を公開",
            url="https://example.com/ir/1",
            published_at="2026-02-16T00:00:00+09:00",
            source_label="IRサイト",
            content="決算資料を公開しました",
        )
        self.assertEqual(event_a.fingerprint, event_b.fingerprint)

    def test_composite_source_continues_when_one_source_fails(self) -> None:
        class SuccessSource:
            def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
                return [
                    IntelEvent(
                        ticker=item.ticker,
                        kind=IntelKind.IR,
                        title="決算資料を公開",
                        url="https://example.com/ir/1",
                        published_at="2026-02-15T00:00:00+09:00",
                        source_label="IRサイト",
                        content="決算資料を公開しました",
                    )
                ]

        class FailingSource:
            def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
                raise IntelSourceError("source down")

        item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            ai_enabled=True,
        )
        source = CompositeIntelSource((SuccessSource(), FailingSource()))

        events = source.fetch_events(item, now_iso="2026-02-15T00:00:00+09:00")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].url, "https://example.com/ir/1")

    def test_composite_source_raises_when_all_sources_fail(self) -> None:
        class FailingSource:
            def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
                raise IntelSourceError("source down")

        item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            ai_enabled=True,
        )
        source = CompositeIntelSource((FailingSource(), FailingSource()))

        with self.assertRaises(IntelSourceError):
            source.fetch_events(item, now_iso="2026-02-15T00:00:00+09:00")


if __name__ == "__main__":
    unittest.main()

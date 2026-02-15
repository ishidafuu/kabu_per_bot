from __future__ import annotations

import unittest

from kabu_per_bot.intelligence import HeuristicAiAnalyzer, IntelEvent, IntelKind
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from kabu_per_bot.intelligence import (
    AiAnalyzeError,
    CompositeIntelSource,
    HeuristicAiAnalyzer,
    IntelEvent,
    IntelKind,
    IntelSourceError,
    VertexGeminiAiAnalyzer,
)
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


class FakeResponse:
    def __init__(self, *, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http error: status={self.status_code}")

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.last_url: str | None = None
        self.last_headers: dict | None = None
        self.last_json: dict | None = None

    def post(self, url: str, *, headers: dict, json: dict, timeout: float) -> FakeResponse:
        del timeout
        self.last_url = url
        self.last_headers = headers
        self.last_json = json
        return self._response


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

    def test_vertex_gemini_ai_analyzer_parses_json_response(self) -> None:
        analyzer = VertexGeminiAiAnalyzer(
            project_id="demo-project",
            location="global",
            model="gemini-2.0-flash-001",
            credentials_provider=lambda: ("dummy-token", "ignored-project"),
            http_client=FakeHttpClient(
                FakeResponse(
                    payload={
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "text": (
                                                '{"summary":"業績見通しを更新","evidence_urls":["https://example.com/ir/1"],'
                                                '"ir_label":"決算資料","sns_label":"該当なし","tone":"ポジ","confidence":"High"}'
                                            )
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                )
            ),
        )
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
            kind=IntelKind.IR,
            title="決算資料を公開",
            url="https://example.com/ir/1",
            published_at="2026-02-15T00:00:00+09:00",
            source_label="IRサイト",
            content="決算資料を公開しました",
        )
        insight = analyzer.analyze(item=item, event=event)
        self.assertEqual(insight.summary, "業績見通しを更新")
        self.assertEqual(insight.ir_label, "決算資料")
        self.assertEqual(insight.sns_label, "該当なし")
        self.assertEqual(insight.tone, "ポジ")
        self.assertEqual(insight.confidence, "High")
        self.assertEqual(insight.evidence_urls, ["https://example.com/ir/1"])
        self.assertEqual(
            analyzer._client.last_json["generationConfig"]["responseMimeType"],
            "application/json",
        )

    def test_vertex_gemini_ai_analyzer_raises_on_invalid_response(self) -> None:
        analyzer = VertexGeminiAiAnalyzer(
            project_id="demo-project",
            credentials_provider=lambda: ("dummy-token", "ignored-project"),
            http_client=FakeHttpClient(FakeResponse(payload={"candidates": []})),
        )
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
            kind=IntelKind.IR,
            title="決算資料を公開",
            url="https://example.com/ir/1",
            published_at="2026-02-15T00:00:00+09:00",
            source_label="IRサイト",
            content="決算資料を公開しました",
        )
        with self.assertRaises(AiAnalyzeError):
            analyzer.analyze(item=item, event=event)

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

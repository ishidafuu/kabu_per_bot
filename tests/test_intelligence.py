from __future__ import annotations

import unittest
from unittest.mock import patch

from kabu_per_bot.intelligence import (
    AiAnalyzeError,
    CompositeIntelSource,
    GrokPromptIntelSource,
    HeuristicAiAnalyzer,
    IntelEvent,
    IntelKind,
    IntelSourceError,
    IRWebsiteIntelSource,
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


class FakeWebResponse:
    def __init__(
        self,
        *,
        status_code: int,
        text: str = "",
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http error: status={self.status_code}")


class FakeWebClient:
    def __init__(self, routes: dict[str, FakeWebResponse]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> FakeWebResponse:
        del timeout
        self.calls.append(url)
        route = self._routes.get(url)
        if route is None:
            raise RuntimeError(f"route not found: {url}")
        return route


class FakeGrokResponse:
    def __init__(self, *, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http error: status={self.status_code}")

    def json(self) -> dict:
        return self._payload


class FakeGrokClient:
    def __init__(self, responses: list[FakeGrokResponse]) -> None:
        self._responses = responses
        self.calls: list[dict] = []

    def post(self, url: str, *, json: dict, timeout: float):
        del timeout
        self.calls.append({"url": url, "json": json})
        if not self._responses:
            raise RuntimeError("response not configured")
        return self._responses.pop(0)


class IntelligenceTest(unittest.TestCase):
    def _watch_item(self) -> WatchlistItem:
        return WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            ai_enabled=True,
            ir_urls=("https://example.com/ir",),
        )

    def test_heuristic_ai_analyzer_returns_labels(self) -> None:
        analyzer = HeuristicAiAnalyzer()
        item = self._watch_item()
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

    def test_vertex_gemini_ai_analyzer_wraps_credentials_error(self) -> None:
        analyzer = VertexGeminiAiAnalyzer(
            project_id="demo-project",
            credentials_provider=lambda: (_ for _ in ()).throw(RuntimeError("adc failed")),
            http_client=FakeHttpClient(FakeResponse(payload={})),
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
            analyzer.analyze(item=self._watch_item(), event=event)

    def test_ir_website_source_extracts_html_body_content(self) -> None:
        listing_url = "https://example.com/ir"
        detail_url = "https://example.com/ir/notice-1"
        client = FakeWebClient(
            {
                listing_url: FakeWebResponse(
                    status_code=200,
                    text=f'<a href="{detail_url}">2026年3Q 決算説明資料</a>',
                ),
                detail_url: FakeWebResponse(
                    status_code=200,
                    text=(
                        "<html><body>"
                        "<h1>2026年3Q 決算説明資料</h1>"
                        "<p>売上高は前年同期比12%増の100億円、営業利益は20億円でした。</p>"
                        "</body></html>"
                    ),
                ),
            }
        )
        source = IRWebsiteIntelSource(http_client=client)

        events = source.fetch_events(self._watch_item(), now_iso="2026-02-15T00:00:00+09:00")

        self.assertEqual(len(events), 1)
        self.assertIn("売上高は前年同期比12%増", events[0].content)
        self.assertEqual(events[0].url, detail_url)

    def test_ir_website_source_extracts_pdf_body_content(self) -> None:
        listing_url = "https://example.com/ir"
        pdf_url = "https://example.com/ir/report.pdf"
        client = FakeWebClient(
            {
                listing_url: FakeWebResponse(
                    status_code=200,
                    text=f'<a href="{pdf_url}">決算短信</a>',
                ),
                pdf_url: FakeWebResponse(
                    status_code=200,
                    content=b"%PDF-1.7 dummy",
                    headers={"content-type": "application/pdf"},
                ),
            }
        )
        source = IRWebsiteIntelSource(http_client=client)

        with patch(
            "kabu_per_bot.intelligence._extract_pdf_text",
            return_value="売上高100億円 営業利益20億円 経常利益は前年同期比で増加しました",
        ):
            events = source.fetch_events(self._watch_item(), now_iso="2026-02-15T00:00:00+09:00")

        self.assertEqual(len(events), 1)
        self.assertIn("売上高100億円", events[0].content)
        self.assertEqual(events[0].url, pdf_url)

    def test_ir_website_source_accepts_pdf_direct_url(self) -> None:
        pdf_url = "https://example.com/ir/2026_q3_results.pdf"
        watch_item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            ai_enabled=True,
            ir_urls=(pdf_url,),
        )
        client = FakeWebClient(
            {
                pdf_url: FakeWebResponse(
                    status_code=200,
                    content=b"%PDF-1.7 direct",
                    headers={"content-type": "application/pdf"},
                ),
            }
        )
        source = IRWebsiteIntelSource(http_client=client)

        with patch("kabu_per_bot.intelligence._extract_pdf_text", return_value="売上高100億円 営業利益20億円 増益です"):
            events = source.fetch_events(watch_item, now_iso="2026-02-15T00:00:00+09:00")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].url, pdf_url)
        self.assertIn("2026_q3_results", events[0].title)
        self.assertIn("売上高100億円", events[0].content)
        self.assertEqual(client.calls, [pdf_url])

    def test_ir_website_source_falls_back_to_title_when_detail_fetch_fails(self) -> None:
        listing_url = "https://example.com/ir"
        detail_url = "https://example.com/ir/notice-2"
        client = FakeWebClient(
            {
                listing_url: FakeWebResponse(
                    status_code=200,
                    text=f'<a href="{detail_url}">適時開示</a>',
                ),
                detail_url: FakeWebResponse(status_code=500),
            }
        )
        source = IRWebsiteIntelSource(http_client=client)

        events = source.fetch_events(self._watch_item(), now_iso="2026-02-15T00:00:00+09:00")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].content, "適時開示")

    def test_ir_website_source_limits_detail_fetch_count(self) -> None:
        listing_url = "https://example.com/ir"
        detail_a = "https://example.com/ir/a"
        detail_b = "https://example.com/ir/b"
        detail_c = "https://example.com/ir/c"
        client = FakeWebClient(
            {
                listing_url: FakeWebResponse(
                    status_code=200,
                    text=(
                        f'<a href="{detail_a}">開示Aです</a>'
                        f'<a href="{detail_b}">開示Bです</a>'
                        f'<a href="{detail_c}">開示Cです</a>'
                    ),
                ),
                detail_a: FakeWebResponse(status_code=200, text="<p>本文Aです。売上は増加しました。</p>"),
                detail_b: FakeWebResponse(status_code=200, text="<p>本文Bです。営業利益は増加しました。</p>"),
                detail_c: FakeWebResponse(status_code=200, text="<p>本文Cです。経常利益は増加しました。</p>"),
            }
        )
        source = IRWebsiteIntelSource(http_client=client, max_events_per_url=1)

        events = source.fetch_events(self._watch_item(), now_iso="2026-02-15T00:00:00+09:00")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].url, detail_a)
        self.assertEqual(client.calls, [listing_url, detail_a])

    def test_ir_website_source_prioritizes_ir_links_over_navigation(self) -> None:
        listing_url = "https://example.com/ir"
        nav_url = "https://example.com/contact"
        ir_pdf_url = "https://example.com/ir/library/2026_q3.pdf"
        client = FakeWebClient(
            {
                listing_url: FakeWebResponse(
                    status_code=200,
                    text=(
                        f'<a href="{nav_url}">お問い合わせ</a>'
                        f'<a href="{ir_pdf_url}">2026年3Q 決算短信</a>'
                    ),
                ),
                nav_url: FakeWebResponse(status_code=200, text="<p>お問い合わせはこちら</p>"),
                ir_pdf_url: FakeWebResponse(
                    status_code=200,
                    content=b"%PDF-1.7",
                    headers={"content-type": "application/pdf"},
                ),
            }
        )
        source = IRWebsiteIntelSource(http_client=client, max_events_per_url=1)

        with patch("kabu_per_bot.intelligence._extract_pdf_text", return_value="売上高100億円 営業利益20億円 増益です"):
            events = source.fetch_events(self._watch_item(), now_iso="2026-02-15T00:00:00+09:00")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].url, ir_pdf_url)
        self.assertEqual(client.calls, [listing_url, ir_pdf_url])

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

    def test_grok_prompt_source_parses_posts_json(self) -> None:
        client = FakeGrokClient(
            [
                FakeGrokResponse(
                    payload={
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"posts":[{"url":"https://x.com/fuji/status/1",'
                                        '"published_at":"2026-02-15T09:30:00+09:00",'
                                        '"account":"@fuji_ir","source_label":"公式",'
                                        '"summary":"新製品の受注進捗を開示"}]}'
                                    )
                                }
                            }
                        ]
                    }
                )
            ]
        )
        item = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            ai_enabled=True,
            x_official_account="fuji_ir",
        )
        source = GrokPromptIntelSource(
            api_key="dummy-key",
            model="grok-4-1-fast-non-reasoning",
            reasoning_model="grok-4-1-fast-reasoning",
            prompt_template="対象 {ticker} {company_name}",
            http_client=client,
        )

        events = source.fetch_events(item, now_iso="2026-02-15T00:00:00+00:00")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, IntelKind.SNS)
        self.assertEqual(events[0].url, "https://x.com/fuji/status/1")
        self.assertEqual(events[0].title, "@fuji_ir")
        self.assertEqual(events[0].source_label, "公式")

    def test_grok_prompt_source_raises_when_api_key_missing(self) -> None:
        item = self._watch_item()
        source = GrokPromptIntelSource(
            api_key="",
            model="grok-4-1-fast-non-reasoning",
            reasoning_model="grok-4-1-fast-reasoning",
            prompt_template="対象 {ticker}",
        )
        with self.assertRaises(IntelSourceError):
            source.fetch_events(item, now_iso="2026-02-15T00:00:00+00:00")

    def test_grok_prompt_source_fallbacks_to_reasoning_model(self) -> None:
        client = FakeGrokClient(
            [
                FakeGrokResponse(payload={"choices": [{"message": {"content": '{"posts":[]}'}}]}),
                FakeGrokResponse(
                    payload={
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"posts":[{"url":"https://x.com/fuji/status/2",'
                                        '"published_at":"2026-02-15T12:00:00+09:00",'
                                        '"account":"@fuji_ceo","source_label":"役員",'
                                        '"summary":"設備投資の進捗を投稿"}]}'
                                    )
                                }
                            }
                        ]
                    }
                ),
            ]
        )
        source = GrokPromptIntelSource(
            api_key="dummy-key",
            model="grok-4-1-fast-non-reasoning",
            reasoning_model="grok-4-1-fast-reasoning",
            prompt_template="対象 {ticker}",
            http_client=client,
        )

        events = source.fetch_events(self._watch_item(), now_iso="2026-02-15T00:00:00+00:00")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].url, "https://x.com/fuji/status/2")
        self.assertEqual(client.calls[0]["json"]["model"], "grok-4-1-fast-non-reasoning")
        self.assertEqual(client.calls[1]["json"]["model"], "grok-4-1-fast-reasoning")

    def test_grok_prompt_source_fallbacks_when_first_model_json_invalid(self) -> None:
        client = FakeGrokClient(
            [
                FakeGrokResponse(payload={"choices": [{"message": {"content": "not-json"}}]}),
                FakeGrokResponse(
                    payload={
                        "choices": [
                            {
                                "message": {
                                    "content": (
                                        '{"posts":[{"url":"https://x.com/fuji/status/3",'
                                        '"published_at":"2026-02-15T12:30:00+09:00",'
                                        '"account":"@fuji_ir","source_label":"公式",'
                                        '"summary":"工場稼働率の改善を投稿"}]}'
                                    )
                                }
                            }
                        ]
                    }
                ),
            ]
        )
        source = GrokPromptIntelSource(
            api_key="dummy-key",
            model="grok-4-1-fast-non-reasoning",
            reasoning_model="grok-4-1-fast-reasoning",
            prompt_template="対象 {ticker}",
            http_client=client,
        )

        events = source.fetch_events(self._watch_item(), now_iso="2026-02-15T00:00:00+00:00")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].url, "https://x.com/fuji/status/3")
        self.assertEqual(client.calls[0]["json"]["model"], "grok-4-1-fast-non-reasoning")
        self.assertEqual(client.calls[1]["json"]["model"], "grok-4-1-fast-reasoning")

    def test_grok_prompt_source_skips_fetch_by_gate(self) -> None:
        client = FakeGrokClient(
            [
                FakeGrokResponse(
                    payload={
                        "choices": [
                            {
                                "message": {
                                    "content": '{"posts":[{"url":"https://x.com/fuji/status/1","summary":"dummy"}]}'
                                }
                            }
                        ]
                    }
                )
            ]
        )
        source = GrokPromptIntelSource(
            api_key="dummy-key",
            model="grok-4-1-fast-non-reasoning",
            reasoning_model="grok-4-1-fast-reasoning",
            prompt_template="対象 {ticker}",
            fetch_gate=lambda item, now_iso: False,
            http_client=client,
        )

        events = source.fetch_events(self._watch_item(), now_iso="2026-02-15T00:00:00+00:00")

        self.assertEqual(events, [])
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()

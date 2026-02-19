from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.intelligence import AiInsight, IntelEvent, IntelKind, IntelSourceError
from kabu_per_bot.intelligence_pipeline import IntelligencePipelineConfig, run_intelligence_pipeline
from kabu_per_bot.pipeline import NotificationExecutionMode
from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem, XAccountLink


@dataclass
class InMemorySeenRepo:
    seen: set[str] = field(default_factory=set)
    seen_tickers: set[str] = field(default_factory=set)
    seen_ticker_kinds: set[tuple[str, IntelKind]] = field(default_factory=set)

    def exists(self, fingerprint: str) -> bool:
        return fingerprint in self.seen

    def has_any_for_ticker(self, ticker: str) -> bool:
        return ticker in self.seen_tickers

    def has_any_for_ticker_and_kind(self, ticker: str, kind: IntelKind) -> bool:
        return (ticker, kind) in self.seen_ticker_kinds

    def mark_seen(self, event: IntelEvent, *, seen_at: str) -> None:
        del seen_at
        self.seen.add(event.fingerprint)
        self.seen_tickers.add(event.ticker)
        self.seen_ticker_kinds.add((event.ticker, event.kind))


@dataclass
class InMemoryLogRepo:
    rows: list[NotificationLogEntry] = field(default_factory=list)

    def append(self, entry: NotificationLogEntry) -> None:
        self.rows.append(entry)

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        filtered = [row for row in self.rows if row.ticker == ticker]
        return list(reversed(filtered))[:limit]


@dataclass
class CollectSender:
    messages: list[str] = field(default_factory=list)

    def send(self, message: str) -> None:
        self.messages.append(message)


class StaticSource:
    def __init__(self, events: list[IntelEvent]) -> None:
        self._events = events

    def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
        return [row for row in self._events if row.ticker == item.ticker]


class FailingSource:
    def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
        raise IntelSourceError("source down")


class StaticAnalyzer:
    def analyze(self, *, item: WatchlistItem, event: IntelEvent) -> AiInsight:
        return AiInsight(
            summary=f"{event.title} を検知",
            evidence_urls=[event.url],
            ir_label="適時開示" if event.kind is IntelKind.IR else "該当なし",
            sns_label="公式" if event.kind is IntelKind.SNS else "該当なし",
            tone="ニュートラル",
            confidence="Med",
        )


class IntelligencePipelineTest(unittest.TestCase):
    def _watch_item(
        self,
        *,
        ai_enabled: bool = True,
        ticker: str = "3901:TSE",
        name: str = "富士フイルム",
    ) -> WatchlistItem:
        return WatchlistItem(
            ticker=ticker,
            name=name,
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            ai_enabled=ai_enabled,
            ir_urls=("https://example.com/ir",),
            x_official_account="fujifilm_ir",
            x_executive_accounts=(XAccountLink(handle="exec_1", role="CEO"),),
        )

    def test_run_intelligence_pipeline_sends_update_and_ai_notifications(self) -> None:
        source = StaticSource(
            events=[
                IntelEvent(
                    ticker="3901:TSE",
                    kind=IntelKind.IR,
                    title="決算資料を公開",
                    url="https://example.com/ir/1",
                    published_at="2026-02-15T00:00:00+09:00",
                    source_label="IRサイト",
                    content="決算資料を公開しました",
                ),
                IntelEvent(
                    ticker="3901:TSE",
                    kind=IntelKind.SNS,
                    title="@fujifilm_ir",
                    url="https://x.com/fujifilm_ir/status/1",
                    published_at="2026-02-15T00:05:00+09:00",
                    source_label="公式",
                    content="新製品の受注が好調です",
                ),
            ]
        )
        sender = CollectSender()
        log_repo = InMemoryLogRepo()
        seen_repo = InMemorySeenRepo(
            seen_tickers={"3901:TSE"},
            seen_ticker_kinds={("3901:TSE", IntelKind.IR)},
        )
        result = run_intelligence_pipeline(
            watchlist_items=[self._watch_item(ai_enabled=True)],
            source=source,
            analyzer=StaticAnalyzer(),
            seen_repo=seen_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=IntelligencePipelineConfig(
                cooldown_hours=2,
                now_iso="2026-02-15T00:10:00+09:00",
                intel_notification_max_age_days=14,
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )
        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 4)
        self.assertEqual(result.errors, 0)
        self.assertEqual(len(sender.messages), 4)
        self.assertEqual(len(seen_repo.seen), 2)

    def test_source_failure_emits_data_unknown(self) -> None:
        sender = CollectSender()
        log_repo = InMemoryLogRepo()
        seen_repo = InMemorySeenRepo()
        result = run_intelligence_pipeline(
            watchlist_items=[self._watch_item(ai_enabled=False)],
            source=FailingSource(),
            analyzer=StaticAnalyzer(),
            seen_repo=seen_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=IntelligencePipelineConfig(
                cooldown_hours=2,
                now_iso="2026-02-15T00:10:00+09:00",
                intel_notification_max_age_days=14,
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )
        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(result.errors, 1)
        self.assertIn("【データ不明】", sender.messages[0])

    def test_source_failure_emits_data_unknown_with_discord_variant_channel(self) -> None:
        sender = CollectSender()
        log_repo = InMemoryLogRepo()
        seen_repo = InMemorySeenRepo()
        result = run_intelligence_pipeline(
            watchlist_items=[self._watch_item(ai_enabled=False)],
            source=FailingSource(),
            analyzer=StaticAnalyzer(),
            seen_repo=seen_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=IntelligencePipelineConfig(
                cooldown_hours=2,
                now_iso="2026-02-15T00:10:00+09:00",
                intel_notification_max_age_days=14,
                channel="DISCORD_INTELLIGENCE",
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )
        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(result.errors, 1)
        self.assertIn("【データ不明】", sender.messages[0])

    def test_initial_run_marks_seen_without_sending_notifications(self) -> None:
        source = StaticSource(
            events=[
                IntelEvent(
                    ticker="3901:TSE",
                    kind=IntelKind.IR,
                    title="決算資料を公開",
                    url="https://example.com/ir/1",
                    published_at="2026-02-15T00:00:00+09:00",
                    source_label="IRサイト",
                    content="決算資料を公開しました",
                )
            ]
        )
        sender = CollectSender()
        log_repo = InMemoryLogRepo()
        seen_repo = InMemorySeenRepo()
        result = run_intelligence_pipeline(
            watchlist_items=[self._watch_item(ai_enabled=True)],
            source=source,
            analyzer=StaticAnalyzer(),
            seen_repo=seen_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=IntelligencePipelineConfig(
                cooldown_hours=2,
                now_iso="2026-02-15T00:10:00+09:00",
                intel_notification_max_age_days=14,
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 0)
        self.assertEqual(result.skipped_notifications, 1)
        self.assertEqual(len(sender.messages), 0)
        self.assertEqual(len(seen_repo.seen), 1)

    def test_initial_run_sns_event_is_sent(self) -> None:
        source = StaticSource(
            events=[
                IntelEvent(
                    ticker="3901:TSE",
                    kind=IntelKind.SNS,
                    title="@fujifilm_ir",
                    url="https://x.com/fujifilm_ir/status/1",
                    published_at="2026-02-15T00:05:00+09:00",
                    source_label="公式",
                    content="新製品の受注が好調です",
                )
            ]
        )
        sender = CollectSender()
        log_repo = InMemoryLogRepo()
        seen_repo = InMemorySeenRepo()
        result = run_intelligence_pipeline(
            watchlist_items=[self._watch_item(ai_enabled=False)],
            source=source,
            analyzer=StaticAnalyzer(),
            seen_repo=seen_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=IntelligencePipelineConfig(
                cooldown_hours=2,
                now_iso="2026-02-15T00:10:00+09:00",
                intel_notification_max_age_days=14,
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 2)
        self.assertEqual(result.skipped_notifications, 0)
        self.assertEqual(len(sender.messages), 2)
        self.assertIn("【SNS注目】", sender.messages[0])
        self.assertIn("【AI注目】", sender.messages[1])
        self.assertEqual(len(seen_repo.seen), 1)

    def test_ir_initial_run_uses_ir_history_only(self) -> None:
        source = StaticSource(
            events=[
                IntelEvent(
                    ticker="3901:TSE",
                    kind=IntelKind.IR,
                    title="決算資料を公開",
                    url="https://example.com/ir/1",
                    published_at="2026-02-15T00:00:00+09:00",
                    source_label="IRサイト",
                    content="決算資料を公開しました",
                )
            ]
        )
        sender = CollectSender()
        log_repo = InMemoryLogRepo()
        seen_repo = InMemorySeenRepo(
            seen_tickers={"3901:TSE"},
            seen_ticker_kinds={("3901:TSE", IntelKind.SNS)},
        )
        result = run_intelligence_pipeline(
            watchlist_items=[self._watch_item(ai_enabled=False)],
            source=source,
            analyzer=StaticAnalyzer(),
            seen_repo=seen_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=IntelligencePipelineConfig(
                cooldown_hours=2,
                now_iso="2026-02-15T00:10:00+09:00",
                intel_notification_max_age_days=14,
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 0)
        self.assertEqual(result.skipped_notifications, 1)
        self.assertEqual(len(sender.messages), 0)
        self.assertIn(("3901:TSE", IntelKind.IR), seen_repo.seen_ticker_kinds)

    def test_old_event_is_marked_seen_and_skipped_when_out_of_range(self) -> None:
        source = StaticSource(
            events=[
                IntelEvent(
                    ticker="3901:TSE",
                    kind=IntelKind.IR,
                    title="古い決算資料",
                    url="https://example.com/ir/old",
                    published_at="2025-01-01T00:00:00+09:00",
                    source_label="IRサイト",
                    content="古い資料です",
                )
            ]
        )
        sender = CollectSender()
        log_repo = InMemoryLogRepo()
        seen_repo = InMemorySeenRepo(
            seen_tickers={"3901:TSE"},
            seen_ticker_kinds={("3901:TSE", IntelKind.IR)},
        )
        result = run_intelligence_pipeline(
            watchlist_items=[self._watch_item(ai_enabled=True)],
            source=source,
            analyzer=StaticAnalyzer(),
            seen_repo=seen_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=IntelligencePipelineConfig(
                cooldown_hours=2,
                now_iso="2026-02-15T00:10:00+09:00",
                intel_notification_max_age_days=14,
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 0)
        self.assertEqual(result.skipped_notifications, 1)
        self.assertEqual(len(sender.messages), 0)
        self.assertEqual(len(seen_repo.seen), 1)

    def test_event_without_published_at_is_sent_after_initial_run(self) -> None:
        source = StaticSource(
            events=[
                IntelEvent(
                    ticker="3901:TSE",
                    kind=IntelKind.IR,
                    title="公開日不明のIR",
                    url="https://example.com/ir/undated",
                    published_at="",
                    source_label="IRサイト",
                    content="本文",
                )
            ]
        )
        sender = CollectSender()
        log_repo = InMemoryLogRepo()
        seen_repo = InMemorySeenRepo(
            seen_tickers={"3901:TSE"},
            seen_ticker_kinds={("3901:TSE", IntelKind.IR)},
        )
        result = run_intelligence_pipeline(
            watchlist_items=[self._watch_item(ai_enabled=False)],
            source=source,
            analyzer=StaticAnalyzer(),
            seen_repo=seen_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=IntelligencePipelineConfig(
                cooldown_hours=2,
                now_iso="2026-02-15T00:10:00+09:00",
                intel_notification_max_age_days=14,
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 2)
        self.assertEqual(result.skipped_notifications, 0)
        self.assertEqual(len(sender.messages), 2)
        self.assertIn("【IR更新】", sender.messages[0])
        self.assertIn("【AI注目】", sender.messages[1])

    def test_sends_update_then_ai_without_interleaving_other_ticker(self) -> None:
        source = StaticSource(
            events=[
                IntelEvent(
                    ticker="3901:TSE",
                    kind=IntelKind.IR,
                    title="決算資料を公開",
                    url="https://example.com/ir/1",
                    published_at="2026-02-15T00:00:00+09:00",
                    source_label="IRサイト",
                    content="決算資料を公開しました",
                ),
                IntelEvent(
                    ticker="9504:TSE",
                    kind=IntelKind.IR,
                    title="決算短信を公開",
                    url="https://example.com/ir/9504",
                    published_at="2026-02-15T00:00:00+09:00",
                    source_label="IRサイト",
                    content="決算短信を公開しました",
                ),
            ]
        )
        sender = CollectSender()
        log_repo = InMemoryLogRepo()
        seen_repo = InMemorySeenRepo(
            seen_tickers={"3901:TSE", "9504:TSE"},
            seen_ticker_kinds={("3901:TSE", IntelKind.IR), ("9504:TSE", IntelKind.IR)},
        )
        result = run_intelligence_pipeline(
            watchlist_items=[
                self._watch_item(ai_enabled=False, ticker="3901:TSE", name="富士フイルム"),
                self._watch_item(ai_enabled=False, ticker="9504:TSE", name="北海道電力"),
            ],
            source=source,
            analyzer=StaticAnalyzer(),
            seen_repo=seen_repo,
            notification_log_repo=log_repo,
            sender=sender,
            config=IntelligencePipelineConfig(
                cooldown_hours=2,
                now_iso="2026-02-15T00:10:00+09:00",
                intel_notification_max_age_days=14,
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )

        self.assertEqual(result.processed_tickers, 2)
        self.assertEqual(result.sent_notifications, 4)
        self.assertIn("【IR更新】3901:TSE", sender.messages[0])
        self.assertIn("【AI注目】3901:TSE", sender.messages[1])
        self.assertIn("【IR更新】9504:TSE", sender.messages[2])
        self.assertIn("【AI注目】9504:TSE", sender.messages[3])


if __name__ == "__main__":
    unittest.main()

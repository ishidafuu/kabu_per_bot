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

    def exists(self, fingerprint: str) -> bool:
        return fingerprint in self.seen

    def mark_seen(self, event: IntelEvent, *, seen_at: str) -> None:
        self.seen.add(event.fingerprint)


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
    def _watch_item(self, *, ai_enabled: bool = True) -> WatchlistItem:
        return WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
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
                execution_mode=NotificationExecutionMode.ALL,
                ai_global_enabled=True,
            ),
        )
        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(result.errors, 1)
        self.assertIn("【データ不明】", sender.messages[0])


if __name__ == "__main__":
    unittest.main()

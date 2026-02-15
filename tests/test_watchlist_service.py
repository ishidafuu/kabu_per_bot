from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.watchlist import (
    CreateResult,
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchlistAlreadyExistsError,
    WatchlistHistoryAction,
    WatchlistHistoryRecord,
    WatchlistItem,
    WatchlistLimitExceededError,
    WatchlistNotFoundError,
    WatchlistPersistenceError,
    WatchlistService,
)


@dataclass
class InMemoryWatchlistRepository:
    docs: dict[str, WatchlistItem] = field(default_factory=dict)

    def try_create(self, item: WatchlistItem, *, max_items: int) -> CreateResult:
        if item.ticker in self.docs:
            return CreateResult.DUPLICATE
        if len(self.docs) >= max_items:
            return CreateResult.LIMIT_EXCEEDED
        self.docs[item.ticker] = item
        return CreateResult.CREATED

    def count(self) -> int:
        return len(self.docs)

    def get(self, ticker: str) -> WatchlistItem | None:
        return self.docs.get(ticker)

    def list_all(self) -> list[WatchlistItem]:
        return sorted(self.docs.values(), key=lambda item: item.ticker)

    def create(self, item: WatchlistItem) -> None:
        self.docs[item.ticker] = item

    def update(self, item: WatchlistItem) -> None:
        self.docs[item.ticker] = item

    def delete(self, ticker: str) -> bool:
        if ticker not in self.docs:
            return False
        del self.docs[ticker]
        return True


@dataclass
class InMemoryWatchlistHistoryRepository:
    records: list[WatchlistHistoryRecord] = field(default_factory=list)

    def append(self, record: WatchlistHistoryRecord) -> None:
        self.records.append(record)


class FailingWatchlistHistoryRepository:
    def append(self, record: WatchlistHistoryRecord) -> None:
        raise RuntimeError(f"history append failed: {record.record_id}")


class WatchlistServiceTest(unittest.TestCase):
    def test_add_list_update_delete(self) -> None:
        repo = InMemoryWatchlistRepository()
        service = WatchlistService(repo)

        created = service.add_item(
            ticker="3901:tse",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            now_iso="2026-02-12T00:00:00+00:00",
        )
        self.assertEqual(created.ticker, "3901:TSE")
        self.assertEqual(len(service.list_items()), 1)

        updated = service.update_item(
            "3901:TSE",
            metric_type=MetricType.PSR,
            notify_channel=NotifyChannel.OFF,
            notify_timing=NotifyTiming.AT_21,
            now_iso="2026-02-13T00:00:00+00:00",
        )
        fetched = service.get_item("3901:TSE")
        self.assertEqual(updated.metric_type, MetricType.PSR)
        self.assertEqual(fetched.notify_channel, NotifyChannel.OFF)
        self.assertEqual(fetched.notify_timing, NotifyTiming.AT_21)
        self.assertEqual(fetched.updated_at, "2026-02-13T00:00:00+00:00")

        service.delete_item("3901:TSE")
        self.assertEqual(service.list_items(), [])
        with self.assertRaises(WatchlistNotFoundError):
            service.get_item("3901:TSE")

    def test_limit_exceeded_raises(self) -> None:
        repo = InMemoryWatchlistRepository()
        service = WatchlistService(repo, max_items=100)

        for index in range(100):
            service.add_item(
                ticker=f"{1000 + index}:TSE",
                name=f"銘柄{index}",
                metric_type="PER",
                notify_channel="DISCORD",
                notify_timing="IMMEDIATE",
            )

        with self.assertRaises(WatchlistLimitExceededError):
            service.add_item(
                ticker="9999:TSE",
                name="超過銘柄",
                metric_type="PER",
                notify_channel="DISCORD",
                notify_timing="IMMEDIATE",
            )

    def test_duplicate_add_raises(self) -> None:
        repo = InMemoryWatchlistRepository()
        service = WatchlistService(repo)
        service.add_item(
            ticker="3901:TSE",
            name="A",
            metric_type="PER",
            notify_channel="DISCORD",
            notify_timing="IMMEDIATE",
        )
        with self.assertRaises(WatchlistAlreadyExistsError):
            service.add_item(
                ticker="3901:TSE",
                name="A",
                metric_type="PER",
                notify_channel="DISCORD",
                notify_timing="IMMEDIATE",
            )

    def test_update_missing_raises(self) -> None:
        repo = InMemoryWatchlistRepository()
        service = WatchlistService(repo)
        with self.assertRaises(WatchlistNotFoundError):
            service.update_item("3901:TSE", name="A")

    def test_from_document_boolean_parsing(self) -> None:
        item = WatchlistItem.from_document(
            {
                "ticker": "3901:tse",
                "name": "A",
                "metric_type": "per",
                "notify_channel": "discord",
                "notify_timing": "immediate",
                "ai_enabled": "false",
                "is_active": "1",
            }
        )
        self.assertFalse(item.ai_enabled)
        self.assertTrue(item.is_active)

    def test_from_document_invalid_boolean_raises(self) -> None:
        with self.assertRaises(ValueError):
            WatchlistItem.from_document(
                {
                    "ticker": "3901:tse",
                    "name": "A",
                    "metric_type": "per",
                    "notify_channel": "discord",
                    "notify_timing": "immediate",
                    "ai_enabled": "not-bool",
                    "is_active": True,
                }
            )

    def test_add_and_delete_write_history(self) -> None:
        repo = InMemoryWatchlistRepository()
        history_repo = InMemoryWatchlistHistoryRepository()
        service = WatchlistService(repo, history_repository=history_repo)
        service.add_item(
            ticker="3901:tse",
            name="富士フイルム",
            metric_type="PER",
            notify_channel="DISCORD",
            notify_timing="IMMEDIATE",
            now_iso="2026-02-12T00:00:00+00:00",
            reason="初回登録",
        )
        service.delete_item(
            "3901:tse",
            now_iso="2026-02-13T00:00:00+00:00",
            reason="不要",
        )

        self.assertEqual(len(history_repo.records), 2)
        self.assertEqual(history_repo.records[0].action, WatchlistHistoryAction.ADD)
        self.assertEqual(history_repo.records[0].reason, "初回登録")
        self.assertEqual(history_repo.records[1].action, WatchlistHistoryAction.REMOVE)
        self.assertEqual(history_repo.records[1].reason, "不要")

    def test_add_rolls_back_when_history_append_fails(self) -> None:
        repo = InMemoryWatchlistRepository()
        service = WatchlistService(repo, history_repository=FailingWatchlistHistoryRepository())

        with self.assertRaises(WatchlistPersistenceError):
            service.add_item(
                ticker="3901:TSE",
                name="富士フイルム",
                metric_type="PER",
                notify_channel="DISCORD",
                notify_timing="IMMEDIATE",
                now_iso="2026-02-12T00:00:00+00:00",
            )

        self.assertIsNone(repo.get("3901:TSE"))

    def test_delete_rolls_back_when_history_append_fails(self) -> None:
        repo = InMemoryWatchlistRepository()
        seed = WatchlistItem(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            created_at="2026-02-12T00:00:00+00:00",
            updated_at="2026-02-12T00:00:00+00:00",
        )
        repo.create(seed)
        service = WatchlistService(repo, history_repository=FailingWatchlistHistoryRepository())

        with self.assertRaises(WatchlistPersistenceError):
            service.delete_item("3901:TSE", now_iso="2026-02-12T01:00:00+00:00")

        restored = repo.get("3901:TSE")
        self.assertIsNotNone(restored)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.watchlist import (
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchlistAlreadyExistsError,
    WatchlistItem,
    WatchlistLimitExceededError,
    WatchlistNotFoundError,
    WatchlistService,
)


@dataclass
class InMemoryWatchlistRepository:
    docs: dict[str, WatchlistItem] = field(default_factory=dict)

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
            notify_channel=NotifyChannel.BOTH,
            notify_timing=NotifyTiming.AT_21,
            now_iso="2026-02-13T00:00:00+00:00",
        )
        fetched = service.get_item("3901:TSE")
        self.assertEqual(updated.metric_type, MetricType.PSR)
        self.assertEqual(fetched.notify_channel, NotifyChannel.BOTH)
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


if __name__ == "__main__":
    unittest.main()


from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.watchlist import (
    CreateResult,
    EvaluationNotifyMode,
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchPriority,
    WatchlistAlreadyExistsError,
    WatchlistHistoryAction,
    WatchlistHistoryRecord,
    WatchlistItem,
    WatchlistLimitExceededError,
    WatchlistNotFoundError,
    WatchlistPersistenceError,
    WatchlistService,
    XAccountLink,
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
            always_notify_enabled=True,
            now_iso="2026-02-13T00:00:00+00:00",
        )
        fetched = service.get_item("3901:TSE")
        self.assertEqual(updated.metric_type, MetricType.PSR)
        self.assertEqual(fetched.notify_channel, NotifyChannel.OFF)
        self.assertEqual(fetched.notify_timing, NotifyTiming.AT_21)
        self.assertTrue(fetched.always_notify_enabled)
        self.assertEqual(fetched.updated_at, "2026-02-13T00:00:00+00:00")

        service.delete_item("3901:TSE")
        self.assertEqual(service.list_items(), [])
        with self.assertRaises(WatchlistNotFoundError):
            service.get_item("3901:TSE")

    def test_priority_defaults_to_medium_and_can_be_updated(self) -> None:
        repo = InMemoryWatchlistRepository()
        service = WatchlistService(repo)

        created = service.add_item(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
        self.assertEqual(created.priority, WatchPriority.MEDIUM)

        updated = service.update_item(
            "3901:TSE",
            priority=WatchPriority.HIGH,
            now_iso="2026-02-13T00:00:00+00:00",
        )
        self.assertEqual(updated.priority, WatchPriority.HIGH)
        self.assertEqual(updated.updated_at, "2026-02-13T00:00:00+00:00")

    def test_technical_profile_assignment_can_be_saved_and_updated(self) -> None:
        repo = InMemoryWatchlistRepository()
        service = WatchlistService(repo)

        created = service.add_item(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            technical_profile_id="custom_swing_plus",
            technical_profile_manual_override=True,
        )
        self.assertEqual(created.technical_profile_id, "custom_swing_plus")
        self.assertTrue(created.technical_profile_manual_override)

        updated = service.update_item(
            "3901:TSE",
            technical_profile_id="system_large_core",
            technical_profile_manual_override=False,
        )
        self.assertEqual(updated.technical_profile_id, "system_large_core")
        self.assertFalse(updated.technical_profile_manual_override)

    def test_evaluation_settings_defaults_and_update(self) -> None:
        repo = InMemoryWatchlistRepository()
        service = WatchlistService(repo)

        created = service.add_item(
            ticker="3901:TSE",
            name="富士フイルム",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
        )
        self.assertFalse(created.evaluation_enabled)
        self.assertEqual(created.evaluation_notify_mode, EvaluationNotifyMode.ALERT_ONLY)
        self.assertEqual(created.evaluation_top_n, 3)
        self.assertEqual(created.evaluation_min_strength, 4)

        updated = service.update_item(
            "3901:TSE",
            evaluation_enabled=True,
            evaluation_notify_mode=EvaluationNotifyMode.ALERT_ONLY,
            evaluation_top_n=5,
            evaluation_min_strength=5,
        )
        self.assertTrue(updated.evaluation_enabled)
        self.assertEqual(updated.evaluation_notify_mode, EvaluationNotifyMode.ALERT_ONLY)
        self.assertEqual(updated.evaluation_top_n, 5)
        self.assertEqual(updated.evaluation_min_strength, 5)

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
                "always_notify_enabled": "true",
                "ai_enabled": "false",
                "is_active": "1",
                "technical_profile_manual_override": "1",
            }
        )
        self.assertTrue(item.always_notify_enabled)
        self.assertTrue(item.ai_enabled)
        self.assertTrue(item.is_active)
        self.assertTrue(item.technical_profile_manual_override)

    def test_from_document_legacy_notify_channel_maps_to_discord(self) -> None:
        for legacy_value in ("LINE", "line", "BOTH", "both"):
            with self.subTest(legacy_value=legacy_value):
                with self.assertLogs("kabu_per_bot.watchlist", level="WARNING") as captured:
                    item = WatchlistItem.from_document(
                        {
                            "ticker": "3901:tse",
                            "name": "A",
                            "metric_type": "per",
                            "notify_channel": legacy_value,
                            "notify_timing": "immediate",
                        }
                    )
                self.assertEqual(item.notify_channel, NotifyChannel.DISCORD)
                self.assertIn("旧notify_channel値を互換変換", captured.output[0])

    def test_item_supports_ir_and_x_links(self) -> None:
        repo = InMemoryWatchlistRepository()
        service = WatchlistService(repo)

        created = service.add_item(
            ticker="3901:TSE",
            name="A",
            metric_type="PER",
            notify_channel="DISCORD",
            notify_timing="IMMEDIATE",
            ir_urls=["https://example.com/ir", "https://example.com/ir"],
            x_official_account="@ExampleIR",
            x_executive_accounts=[
                {"handle": "@exec_a", "role": "CEO"},
                {"handle": "exec_a", "role": "重複"},
                XAccountLink(handle="exec_b", role=None),
            ],
        )
        self.assertEqual(created.ir_urls, ("https://example.com/ir",))
        self.assertEqual(created.x_official_account, "ExampleIR")
        self.assertEqual([entry.handle for entry in created.x_executive_accounts], ["exec_a", "exec_b"])

        updated = service.update_item(
            "3901:TSE",
            ir_urls=["https://example.com/ir2"],
            x_official_account="official_2",
            x_executive_accounts=[{"handle": "exec_c", "role": "CFO"}],
        )
        self.assertEqual(updated.ir_urls, ("https://example.com/ir2",))
        self.assertEqual(updated.x_official_account, "official_2")
        self.assertEqual([(entry.handle, entry.role) for entry in updated.x_executive_accounts], [("exec_c", "CFO")])

    def test_from_document_invalid_boolean_raises(self) -> None:
        with self.assertRaises(ValueError):
            WatchlistItem.from_document(
                {
                    "ticker": "3901:tse",
                    "name": "A",
                    "metric_type": "per",
                    "notify_channel": "discord",
                    "notify_timing": "immediate",
                    "always_notify_enabled": "not-bool",
                    "ai_enabled": "not-bool",
                    "is_active": True,
                }
            )

    def test_from_document_invalid_evaluation_int_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            WatchlistItem.from_document(
                {
                    "ticker": "3901:tse",
                    "name": "A",
                    "metric_type": "per",
                    "notify_channel": "discord",
                    "notify_timing": "immediate",
                    "evaluation_top_n": 0,
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

from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.grok_sns_settings import GrokSnsSettings
from kabu_per_bot.immediate_schedule import ImmediateSchedule
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings
from kabu_per_bot.storage.firestore_global_settings_repository import (
    FirestoreGlobalSettingsRepository,
    GLOBAL_SETTINGS_DOC_ID,
)
from kabu_per_bot.storage.firestore_schema import COLLECTION_GLOBAL_SETTINGS


@dataclass
class FakeSnapshot:
    exists: bool
    data: dict | None = None

    def to_dict(self) -> dict | None:
        return self.data


@dataclass
class FakeDocumentRef:
    path: str
    db: dict[str, dict] = field(default_factory=dict)

    def set(self, data: dict, merge: bool = False) -> None:
        if merge and self.path in self.db:
            merged = dict(self.db[self.path])
            merged.update(data)
            self.db[self.path] = merged
            return
        self.db[self.path] = dict(data)

    def get(self) -> FakeSnapshot:
        if self.path not in self.db:
            return FakeSnapshot(exists=False, data=None)
        return FakeSnapshot(exists=True, data=dict(self.db[self.path]))


@dataclass
class FakeCollectionRef:
    path: str
    db: dict[str, dict] = field(default_factory=dict)

    def document(self, document_id: str) -> FakeDocumentRef:
        return FakeDocumentRef(path=f"{self.path}/{document_id}", db=self.db)


@dataclass
class FakeFirestoreClient:
    db: dict[str, dict] = field(default_factory=dict)

    def collection(self, name: str) -> FakeCollectionRef:
        return FakeCollectionRef(path=name, db=self.db)


class FirestoreGlobalSettingsRepositoryTest(unittest.TestCase):
    def test_get_returns_empty_when_not_exists(self) -> None:
        repo = FirestoreGlobalSettingsRepository(FakeFirestoreClient())
        self.assertEqual(repo.get_global_settings(), GlobalRuntimeSettings())

    def test_upsert_and_get(self) -> None:
        client = FakeFirestoreClient()
        repo = FirestoreGlobalSettingsRepository(client)
        repo.upsert_global_settings(
            cooldown_hours=4,
            intel_notification_max_age_days=21,
            immediate_schedule=ImmediateSchedule(
                enabled=False,
                timezone="Asia/Tokyo",
                open_window_start="09:30",
                open_window_end="10:30",
                open_window_interval_min=30,
                close_window_start="14:00",
                close_window_end="15:00",
                close_window_interval_min=20,
            ),
            grok_sns_settings=GrokSnsSettings(
                enabled=True,
                scheduled_time="20:40",
                per_ticker_cooldown_hours=12,
                prompt_template="重要SNS投稿を要約し、投稿者・時刻・URLを必ず含めてください。",
            ),
            updated_at="2026-02-18T12:00:00+09:00",
            updated_by="admin-user",
        )

        result = repo.get_global_settings()
        self.assertEqual(result.cooldown_hours, 4)
        self.assertEqual(result.intel_notification_max_age_days, 21)
        self.assertIsNotNone(result.immediate_schedule)
        assert result.immediate_schedule is not None
        self.assertFalse(result.immediate_schedule.enabled)
        self.assertEqual(result.immediate_schedule.open_window_interval_min, 30)
        self.assertIsNotNone(result.grok_sns_settings)
        assert result.grok_sns_settings is not None
        self.assertTrue(result.grok_sns_settings.enabled)
        self.assertEqual(result.grok_sns_settings.scheduled_time, "20:40")
        self.assertEqual(result.updated_by, "admin-user")
        self.assertEqual(result.updated_at, "2026-02-18T03:00:00+00:00")
        self.assertIn(f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}", client.db)

    def test_get_raises_for_invalid_cooldown_hours(self) -> None:
        client = FakeFirestoreClient(
            db={
                f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}": {
                    "cooldown_hours": 0,
                }
            }
        )
        repo = FirestoreGlobalSettingsRepository(client)
        with self.assertRaises(ValueError):
            repo.get_global_settings()

    def test_get_raises_for_invalid_intel_notification_max_age_days(self) -> None:
        client = FakeFirestoreClient(
            db={
                f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}": {
                    "intel_notification_max_age_days": 0,
                }
            }
        )
        repo = FirestoreGlobalSettingsRepository(client)
        with self.assertRaises(ValueError):
            repo.get_global_settings()

    def test_upsert_immediate_schedule_only_keeps_existing_cooldown(self) -> None:
        client = FakeFirestoreClient(
            db={
                f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}": {
                    "cooldown_hours": 6,
                    "intel_notification_max_age_days": 15,
                    "updated_at": "2026-02-18T03:00:00+00:00",
                    "updated_by": "seed-user",
                }
            }
        )
        repo = FirestoreGlobalSettingsRepository(client)

        repo.upsert_global_settings(
            immediate_schedule=ImmediateSchedule.default(),
            updated_at="2026-02-18T12:00:00+09:00",
            updated_by="admin-user",
        )

        result = repo.get_global_settings()
        self.assertEqual(result.cooldown_hours, 6)
        self.assertEqual(result.intel_notification_max_age_days, 15)
        self.assertIsNotNone(result.immediate_schedule)

    def test_get_raises_for_invalid_grok_sns_settings(self) -> None:
        client = FakeFirestoreClient(
            db={
                f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}": {
                    "grok_sns_enabled": True,
                    "grok_sns_scheduled_time": "24:00",
                    "grok_sns_per_ticker_cooldown_hours": 10,
                    "grok_sns_prompt_template": "十分な長さのプロンプトです。十分な長さのプロンプトです。",
                }
            }
        )
        repo = FirestoreGlobalSettingsRepository(client)
        with self.assertRaises(ValueError):
            repo.get_global_settings()

    def test_get_raises_for_invalid_immediate_schedule(self) -> None:
        client = FakeFirestoreClient(
            db={
                f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}": {
                    "immediate_schedule_enabled": True,
                    "immediate_schedule_timezone": "Asia/Tokyo",
                    "immediate_open_window_start": "09:00",
                    "immediate_open_window_end": "10:00",
                    "immediate_open_window_interval_min": 15,
                    "immediate_close_window_start": "09:30",
                    "immediate_close_window_end": "10:30",
                    "immediate_close_window_interval_min": 10,
                }
            }
        )
        repo = FirestoreGlobalSettingsRepository(client)
        with self.assertRaises(ValueError):
            repo.get_global_settings()

    def test_get_raises_for_invalid_numeric_boolean_in_immediate_schedule(self) -> None:
        client = FakeFirestoreClient(
            db={
                f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}": {
                    "immediate_schedule_enabled": 2,
                }
            }
        )
        repo = FirestoreGlobalSettingsRepository(client)
        with self.assertRaises(ValueError):
            repo.get_global_settings()

    def test_get_raises_for_invalid_numeric_boolean_in_grok_settings(self) -> None:
        client = FakeFirestoreClient(
            db={
                f"{COLLECTION_GLOBAL_SETTINGS}/{GLOBAL_SETTINGS_DOC_ID}": {
                    "grok_sns_enabled": -1,
                }
            }
        )
        repo = FirestoreGlobalSettingsRepository(client)
        with self.assertRaises(ValueError):
            repo.get_global_settings()


if __name__ == "__main__":
    unittest.main()

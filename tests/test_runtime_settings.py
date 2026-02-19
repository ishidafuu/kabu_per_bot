from __future__ import annotations

import unittest

from kabu_per_bot.immediate_schedule import ImmediateSchedule
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings, resolve_runtime_settings


class RuntimeSettingsTest(unittest.TestCase):
    def test_resolve_uses_defaults_when_global_empty(self) -> None:
        resolved = resolve_runtime_settings(
            default_cooldown_hours=2,
            global_settings=GlobalRuntimeSettings(),
        )

        self.assertEqual(resolved.cooldown_hours, 2)
        self.assertEqual(resolved.immediate_schedule, ImmediateSchedule.default())
        self.assertEqual(resolved.source, "env_default")

    def test_resolve_uses_firestore_when_schedule_overridden(self) -> None:
        resolved = resolve_runtime_settings(
            default_cooldown_hours=2,
            global_settings=GlobalRuntimeSettings(
                immediate_schedule=ImmediateSchedule(
                    enabled=False,
                    timezone="Asia/Tokyo",
                    open_window_start="09:30",
                    open_window_end="10:30",
                    open_window_interval_min=20,
                    close_window_start="14:00",
                    close_window_end="15:00",
                    close_window_interval_min=20,
                )
            ),
        )

        self.assertEqual(resolved.cooldown_hours, 2)
        self.assertFalse(resolved.immediate_schedule.enabled)
        self.assertEqual(resolved.source, "firestore")


if __name__ == "__main__":
    unittest.main()

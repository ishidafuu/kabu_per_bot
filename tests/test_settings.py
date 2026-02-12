from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from kabu_per_bot.settings import SettingsError, load_settings


class LoadSettingsTest(unittest.TestCase):
    def test_defaults_without_env(self) -> None:
        settings = load_settings(env={}, dotenv_path="does-not-exist.env")

        self.assertEqual(settings.app_env, "development")
        self.assertEqual(settings.timezone, "Asia/Tokyo")
        self.assertEqual(settings.window_1w_days, 5)
        self.assertEqual(settings.window_3m_days, 63)
        self.assertEqual(settings.window_1y_days, 252)
        self.assertEqual(settings.cooldown_hours, 2)
        self.assertEqual(settings.firestore_project_id, "")

    def test_env_override(self) -> None:
        settings = load_settings(
            env={
                "APP_ENV": "production",
                "APP_TIMEZONE": "UTC",
                "WINDOW_1W_DAYS": "7",
                "WINDOW_3M_DAYS": "70",
                "WINDOW_1Y_DAYS": "260",
                "COOLDOWN_HOURS": "3",
                "FIRESTORE_PROJECT_ID": "demo-project",
            },
            dotenv_path="does-not-exist.env",
        )

        self.assertEqual(settings.app_env, "production")
        self.assertEqual(settings.timezone, "UTC")
        self.assertEqual(settings.window_1w_days, 7)
        self.assertEqual(settings.window_3m_days, 70)
        self.assertEqual(settings.window_1y_days, 260)
        self.assertEqual(settings.cooldown_hours, 3)
        self.assertEqual(settings.firestore_project_id, "demo-project")

    def test_dotenv_loaded_when_env_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv = Path(tmpdir) / ".env"
            dotenv.write_text(
                "APP_TIMEZONE=UTC\nWINDOW_1W_DAYS=6\nCOOLDOWN_HOURS=4\n",
                encoding="utf-8",
            )

            settings = load_settings(env={}, dotenv_path=dotenv)

        self.assertEqual(settings.timezone, "UTC")
        self.assertEqual(settings.window_1w_days, 6)
        self.assertEqual(settings.cooldown_hours, 4)
        self.assertEqual(settings.window_3m_days, 63)
        self.assertEqual(settings.window_1y_days, 252)

    def test_env_has_priority_over_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            dotenv = Path(tmpdir) / ".env"
            dotenv.write_text("WINDOW_1W_DAYS=6\n", encoding="utf-8")

            settings = load_settings(
                env={"WINDOW_1W_DAYS": "8"},
                dotenv_path=dotenv,
            )

        self.assertEqual(settings.window_1w_days, 8)

    def test_invalid_integer_raises(self) -> None:
        with self.assertRaises(SettingsError):
            load_settings(
                env={"WINDOW_1W_DAYS": "abc"},
                dotenv_path="does-not-exist.env",
            )

    def test_invalid_timezone_raises(self) -> None:
        with self.assertRaises(SettingsError):
            load_settings(
                env={"APP_TIMEZONE": "Invalid/Timezone"},
                dotenv_path="does-not-exist.env",
            )

    def test_invalid_window_order_raises(self) -> None:
        with self.assertRaises(SettingsError):
            load_settings(
                env={
                    "WINDOW_1W_DAYS": "70",
                    "WINDOW_3M_DAYS": "63",
                    "WINDOW_1Y_DAYS": "252",
                },
                dotenv_path="does-not-exist.env",
            )


if __name__ == "__main__":
    unittest.main()

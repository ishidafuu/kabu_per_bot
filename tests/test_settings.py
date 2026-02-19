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
        self.assertFalse(settings.ai_notifications_enabled)
        self.assertEqual(settings.x_api_bearer_token, "")
        self.assertEqual(settings.grok_api_key, "")
        self.assertEqual(settings.grok_api_base_url, "https://api.x.ai/v1")
        self.assertEqual(settings.grok_model_fast, "grok-4-1-fast-non-reasoning")
        self.assertEqual(settings.grok_model_reasoning, "grok-4-1-fast-reasoning")
        self.assertEqual(settings.vertex_ai_location, "global")
        self.assertEqual(settings.vertex_ai_model, "gemini-2.0-flash-001")
        self.assertFalse(settings.grok_sns_enabled)
        self.assertEqual(settings.grok_sns_scheduled_time, "21:10")
        self.assertEqual(settings.grok_sns_per_ticker_cooldown_hours, 24)
        self.assertGreaterEqual(len(settings.grok_sns_prompt_template), 20)

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
                "AI_NOTIFICATIONS_ENABLED": "true",
                "X_API_BEARER_TOKEN": "token-123",
                "GROK_API_KEY": "grok-key-123",
                "GROK_API_BASE_URL": "https://api.x.ai/v1",
                "GROK_MODEL_FAST": "grok-4-1-fast-non-reasoning",
                "GROK_MODEL_REASONING": "grok-4-1-fast-reasoning",
                "VERTEX_AI_LOCATION": "asia-northeast1",
                "VERTEX_AI_MODEL": "gemini-2.5-flash",
                "GROK_SNS_ENABLED": "true",
                "GROK_SNS_SCHEDULED_TIME": "20:40",
                "GROK_SNS_PER_TICKER_COOLDOWN_HOURS": "12",
                "GROK_SNS_PROMPT_TEMPLATE": "重要SNS投稿を要約し、投稿者とURLを含めてください。",
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
        self.assertTrue(settings.ai_notifications_enabled)
        self.assertEqual(settings.x_api_bearer_token, "token-123")
        self.assertEqual(settings.grok_api_key, "grok-key-123")
        self.assertEqual(settings.grok_api_base_url, "https://api.x.ai/v1")
        self.assertEqual(settings.grok_model_fast, "grok-4-1-fast-non-reasoning")
        self.assertEqual(settings.grok_model_reasoning, "grok-4-1-fast-reasoning")
        self.assertEqual(settings.vertex_ai_location, "asia-northeast1")
        self.assertEqual(settings.vertex_ai_model, "gemini-2.5-flash")
        self.assertTrue(settings.grok_sns_enabled)
        self.assertEqual(settings.grok_sns_scheduled_time, "20:40")
        self.assertEqual(settings.grok_sns_per_ticker_cooldown_hours, 12)
        self.assertEqual(settings.grok_sns_prompt_template, "重要SNS投稿を要約し、投稿者とURLを含めてください。")

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

    def test_invalid_boolean_raises(self) -> None:
        with self.assertRaises(SettingsError):
            load_settings(
                env={"AI_NOTIFICATIONS_ENABLED": "maybe"},
                dotenv_path="does-not-exist.env",
            )

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

    def test_invalid_grok_scheduled_time_raises(self) -> None:
        with self.assertRaises(SettingsError):
            load_settings(
                env={"GROK_SNS_SCHEDULED_TIME": "24:10"},
                dotenv_path="does-not-exist.env",
            )

    def test_invalid_grok_cooldown_upper_bound_raises(self) -> None:
        with self.assertRaises(SettingsError):
            load_settings(
                env={"GROK_SNS_PER_TICKER_COOLDOWN_HOURS": "300"},
                dotenv_path="does-not-exist.env",
            )

    def test_invalid_grok_prompt_length_raises(self) -> None:
        with self.assertRaises(SettingsError):
            load_settings(
                env={"GROK_SNS_PROMPT_TEMPLATE": "短すぎる"},
                dotenv_path="does-not-exist.env",
            )


if __name__ == "__main__":
    unittest.main()

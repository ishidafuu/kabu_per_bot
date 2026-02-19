from __future__ import annotations

import io
import json
from dataclasses import dataclass
from unittest import TestCase
from unittest.mock import patch

import scripts.run_intelligence_job as run_intelligence_job
from kabu_per_bot.grok_sns_settings import GrokSnsSettings
from kabu_per_bot.immediate_schedule import ImmediateSchedule
from kabu_per_bot.pipeline import PipelineResult
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings, RuntimeSettings
from kabu_per_bot.settings import AppSettings


@dataclass
class DummyWatchlistRepo:
    def list_all(self):
        return []


@dataclass
class DummyLogRepo:
    pass


@dataclass
class DummySeenRepo:
    pass


@dataclass
class DummyRecentLog:
    category: str
    sent_at: str


class RunIntelligenceJobScriptTest(TestCase):
    def test_main_stdout_outputs_summary_json(self) -> None:
        args = run_intelligence_job.argparse.Namespace(
            now_iso="2026-02-12T09:00:00+00:00",
            execution_mode="all",
            intel_source="all",
            respect_grok_schedule=False,
            discord_webhook_url="",
            stdout=True,
        )
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="token",
        )
        with (
            patch.object(run_intelligence_job, "parse_args", return_value=args),
            patch.object(run_intelligence_job, "load_settings", return_value=settings),
            patch.object(run_intelligence_job, "_create_firestore_client", return_value=object()),
            patch.object(run_intelligence_job, "FirestoreWatchlistRepository", return_value=DummyWatchlistRepo()),
            patch.object(run_intelligence_job, "FirestoreNotificationLogRepository", return_value=DummyLogRepo()),
            patch.object(run_intelligence_job, "FirestoreIntelSeenRepository", return_value=DummySeenRepo()),
            patch.object(
                run_intelligence_job,
                "run_intelligence_pipeline",
                return_value=PipelineResult(processed_tickers=1, sent_notifications=2, skipped_notifications=0, errors=0),
            ),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_intelligence_job.main()
        self.assertEqual(code, 0)
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        payload = json.loads(lines[-1])
        self.assertEqual(payload, {"processed_tickers": 1, "sent_notifications": 2, "skipped_notifications": 0, "errors": 0})

    def test_resolve_execution_mode(self) -> None:
        self.assertEqual(run_intelligence_job._resolve_execution_mode("daily").value, "DAILY")
        self.assertEqual(run_intelligence_job._resolve_execution_mode("at_21").value, "AT_21")

    def test_main_prefers_firestore_global_settings_for_cooldown(self) -> None:
        args = run_intelligence_job.argparse.Namespace(
            now_iso="2026-02-12T09:00:00+00:00",
            execution_mode="all",
            intel_source="all",
            respect_grok_schedule=False,
            discord_webhook_url="",
            stdout=True,
        )
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="token",
        )
        fake_global_repo = type(
            "FakeGlobalSettingsRepository",
            (),
            {"get_global_settings": lambda self: GlobalRuntimeSettings(cooldown_hours=7)},
        )()

        with (
            patch.object(run_intelligence_job, "parse_args", return_value=args),
            patch.object(run_intelligence_job, "load_settings", return_value=settings),
            patch.object(run_intelligence_job, "_create_firestore_client", return_value=object()),
            patch.object(run_intelligence_job, "FirestoreWatchlistRepository", return_value=DummyWatchlistRepo()),
            patch.object(run_intelligence_job, "FirestoreNotificationLogRepository", return_value=DummyLogRepo()),
            patch.object(run_intelligence_job, "FirestoreIntelSeenRepository", return_value=DummySeenRepo()),
            patch.object(run_intelligence_job, "FirestoreGlobalSettingsRepository", return_value=fake_global_repo),
            patch.object(run_intelligence_job, "run_intelligence_pipeline", return_value=PipelineResult()) as mocked_pipeline,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            code = run_intelligence_job.main()
        self.assertEqual(code, 0)
        config = mocked_pipeline.call_args.kwargs["config"]
        self.assertEqual(config.cooldown_hours, 7)
        self.assertEqual(config.intel_notification_max_age_days, 30)
        self.assertEqual(config.channel, run_intelligence_job.DISCORD_INTELLIGENCE_CHANNEL)

    def test_main_respect_grok_schedule_skips_when_not_scheduled_minute(self) -> None:
        args = run_intelligence_job.argparse.Namespace(
            now_iso="2026-02-19T06:00:00+00:00",  # JST 15:00
            execution_mode="all",
            intel_source="all",
            respect_grok_schedule=True,
            discord_webhook_url="",
            stdout=True,
        )
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="token",
        )
        runtime_settings = RuntimeSettings(
            cooldown_hours=2,
            immediate_schedule=ImmediateSchedule.default(),
            source="firestore",
            grok_sns_settings=GrokSnsSettings(
                enabled=True,
                scheduled_time="16:00",
                per_ticker_cooldown_hours=24,
                prompt_template="対象 {ticker}",
            ),
        )
        with (
            patch.object(run_intelligence_job, "parse_args", return_value=args),
            patch.object(run_intelligence_job, "load_settings", return_value=settings),
            patch.object(run_intelligence_job, "_create_firestore_client", return_value=object()),
            patch.object(run_intelligence_job, "_resolve_runtime_config", return_value=runtime_settings),
            patch.object(run_intelligence_job, "run_intelligence_pipeline") as mocked_pipeline,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_intelligence_job.main()
        self.assertEqual(code, 0)
        mocked_pipeline.assert_not_called()
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        payload = json.loads(lines[-1])
        self.assertEqual(payload, {"processed_tickers": 0, "sent_notifications": 0, "skipped_notifications": 0, "errors": 0})

    def test_main_respect_grok_schedule_skip_does_not_require_webhook(self) -> None:
        args = run_intelligence_job.argparse.Namespace(
            now_iso="2026-02-19T06:00:00+00:00",  # JST 15:00
            execution_mode="all",
            intel_source="all",
            respect_grok_schedule=True,
            discord_webhook_url="",
            stdout=False,
        )
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="token",
        )
        runtime_settings = RuntimeSettings(
            cooldown_hours=2,
            immediate_schedule=ImmediateSchedule.default(),
            source="firestore",
            grok_sns_settings=GrokSnsSettings(
                enabled=True,
                scheduled_time="16:00",
                per_ticker_cooldown_hours=24,
                prompt_template="対象 {ticker}",
            ),
        )
        with (
            patch.object(run_intelligence_job, "parse_args", return_value=args),
            patch.object(run_intelligence_job, "load_settings", return_value=settings),
            patch.object(run_intelligence_job, "_create_firestore_client", return_value=object()),
            patch.object(run_intelligence_job, "_resolve_runtime_config", return_value=runtime_settings),
            patch.object(run_intelligence_job, "run_intelligence_pipeline") as mocked_pipeline,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_intelligence_job.main()
        self.assertEqual(code, 0)
        mocked_pipeline.assert_not_called()
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        payload = json.loads(lines[-1])
        self.assertEqual(payload, {"processed_tickers": 0, "sent_notifications": 0, "skipped_notifications": 0, "errors": 0})

    def test_main_respect_grok_schedule_scheduled_minute_requires_webhook(self) -> None:
        args = run_intelligence_job.argparse.Namespace(
            now_iso="2026-02-19T07:00:00+00:00",  # JST 16:00
            execution_mode="all",
            intel_source="all",
            respect_grok_schedule=True,
            discord_webhook_url="",
            stdout=False,
        )
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="token",
        )
        runtime_settings = RuntimeSettings(
            cooldown_hours=2,
            immediate_schedule=ImmediateSchedule.default(),
            source="firestore",
            grok_sns_settings=GrokSnsSettings(
                enabled=True,
                scheduled_time="16:00",
                per_ticker_cooldown_hours=24,
                prompt_template="対象 {ticker}",
            ),
        )
        with (
            patch.object(run_intelligence_job, "parse_args", return_value=args),
            patch.object(run_intelligence_job, "load_settings", return_value=settings),
            patch.object(run_intelligence_job, "_create_firestore_client", return_value=object()),
            patch.object(run_intelligence_job, "_resolve_runtime_config", return_value=runtime_settings),
        ):
            with self.assertRaises(ValueError):
                run_intelligence_job.main()

    def test_build_intel_source_includes_grok_when_enabled(self) -> None:
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="",
            grok_api_key="dummy-key",
            grok_model_fast="grok-4-1-fast-non-reasoning",
            grok_model_reasoning="grok-4-1-fast-reasoning",
        )
        runtime_settings = RuntimeSettings(
            cooldown_hours=2,
            immediate_schedule=ImmediateSchedule.default(),
            source="firestore",
            grok_sns_settings=GrokSnsSettings(
                enabled=True,
                scheduled_time="21:10",
                per_ticker_cooldown_hours=24,
                prompt_template="対象 {ticker}",
            ),
        )

        with (
            patch.object(run_intelligence_job, "IRWebsiteIntelSource", return_value="ir-source"),
            patch.object(run_intelligence_job, "GrokPromptIntelSource", return_value="grok-source"),
        ):
            source = run_intelligence_job._build_intel_source(
                settings=settings,
                runtime_settings=runtime_settings,
                intel_source="all",
            )

        self.assertEqual(source.sources, ("ir-source", "grok-source"))

    def test_build_intel_source_skips_grok_when_disabled(self) -> None:
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="",
        )
        runtime_settings = RuntimeSettings(
            cooldown_hours=2,
            immediate_schedule=ImmediateSchedule.default(),
            source="firestore",
            grok_sns_settings=GrokSnsSettings(
                enabled=False,
                scheduled_time="21:10",
                per_ticker_cooldown_hours=24,
                prompt_template="対象 {ticker}",
            ),
        )

        with (
            patch.object(run_intelligence_job, "IRWebsiteIntelSource", return_value="ir-source"),
            patch.object(run_intelligence_job, "GrokPromptIntelSource", return_value="grok-source"),
        ):
            source = run_intelligence_job._build_intel_source(
                settings=settings,
                runtime_settings=runtime_settings,
                intel_source="all",
            )

        self.assertEqual(source.sources, ("ir-source",))

    def test_build_intel_source_skips_grok_when_not_scheduled_minute(self) -> None:
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="",
            grok_api_key="dummy-key",
            grok_model_fast="grok-4-1-fast-non-reasoning",
            grok_model_reasoning="grok-4-1-fast-reasoning",
        )
        runtime_settings = RuntimeSettings(
            cooldown_hours=2,
            immediate_schedule=ImmediateSchedule.default(),
            source="firestore",
            grok_sns_settings=GrokSnsSettings(
                enabled=True,
                scheduled_time="21:10",
                per_ticker_cooldown_hours=24,
                prompt_template="対象 {ticker}",
            ),
        )

        with (
            patch.object(run_intelligence_job, "IRWebsiteIntelSource", return_value="ir-source"),
            patch.object(run_intelligence_job, "GrokPromptIntelSource", return_value="grok-source"),
        ):
            source = run_intelligence_job._build_intel_source(
                settings=settings,
                runtime_settings=runtime_settings,
                intel_source="all",
                now_iso="2026-02-19T12:00:00+00:00",  # JST 21:00
            )

        self.assertEqual(source.sources, ("ir-source",))

    def test_build_intel_source_ir_only_excludes_grok(self) -> None:
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="",
            grok_api_key="dummy-key",
            grok_model_fast="grok-4-1-fast-non-reasoning",
            grok_model_reasoning="grok-4-1-fast-reasoning",
        )
        runtime_settings = RuntimeSettings(
            cooldown_hours=2,
            immediate_schedule=ImmediateSchedule.default(),
            source="firestore",
            grok_sns_settings=GrokSnsSettings(
                enabled=True,
                scheduled_time="21:10",
                per_ticker_cooldown_hours=24,
                prompt_template="対象 {ticker}",
            ),
        )

        with (
            patch.object(run_intelligence_job, "IRWebsiteIntelSource", return_value="ir-source"),
            patch.object(run_intelligence_job, "GrokPromptIntelSource", return_value="grok-source"),
        ):
            source = run_intelligence_job._build_intel_source(
                settings=settings,
                runtime_settings=runtime_settings,
                intel_source="ir_only",
            )

        self.assertEqual(source.sources, ("ir-source",))

    def test_build_intel_source_grok_only_excludes_ir(self) -> None:
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="",
            grok_api_key="dummy-key",
            grok_model_fast="grok-4-1-fast-non-reasoning",
            grok_model_reasoning="grok-4-1-fast-reasoning",
        )
        runtime_settings = RuntimeSettings(
            cooldown_hours=2,
            immediate_schedule=ImmediateSchedule.default(),
            source="firestore",
            grok_sns_settings=GrokSnsSettings(
                enabled=True,
                scheduled_time="21:10",
                per_ticker_cooldown_hours=24,
                prompt_template="対象 {ticker}",
            ),
        )

        with (
            patch.object(run_intelligence_job, "IRWebsiteIntelSource", return_value="ir-source"),
            patch.object(run_intelligence_job, "GrokPromptIntelSource", return_value="grok-source"),
        ):
            source = run_intelligence_job._build_intel_source(
                settings=settings,
                runtime_settings=runtime_settings,
                intel_source="grok_only",
            )

        self.assertEqual(source.sources, ("grok-source",))

    def test_main_ir_only_ignores_respect_grok_schedule(self) -> None:
        args = run_intelligence_job.argparse.Namespace(
            now_iso="2026-02-19T06:00:00+00:00",  # JST 15:00
            execution_mode="all",
            intel_source="ir_only",
            respect_grok_schedule=True,
            discord_webhook_url="",
            stdout=True,
        )
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=5,
            window_3m_days=63,
            window_1y_days=252,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=True,
            x_api_bearer_token="token",
        )
        runtime_settings = RuntimeSettings(
            cooldown_hours=2,
            immediate_schedule=ImmediateSchedule.default(),
            source="firestore",
            grok_sns_settings=GrokSnsSettings(
                enabled=True,
                scheduled_time="16:00",
                per_ticker_cooldown_hours=24,
                prompt_template="対象 {ticker}",
            ),
        )
        with (
            patch.object(run_intelligence_job, "parse_args", return_value=args),
            patch.object(run_intelligence_job, "load_settings", return_value=settings),
            patch.object(run_intelligence_job, "_create_firestore_client", return_value=object()),
            patch.object(run_intelligence_job, "_resolve_runtime_config", return_value=runtime_settings),
            patch.object(run_intelligence_job, "FirestoreWatchlistRepository", return_value=DummyWatchlistRepo()),
            patch.object(run_intelligence_job, "FirestoreNotificationLogRepository", return_value=DummyLogRepo()),
            patch.object(run_intelligence_job, "FirestoreIntelSeenRepository", return_value=DummySeenRepo()),
            patch.object(run_intelligence_job, "run_intelligence_pipeline", return_value=PipelineResult()) as mocked_pipeline,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            code = run_intelligence_job.main()
        self.assertEqual(code, 0)
        mocked_pipeline.assert_called_once()

    def test_grok_fetch_gate_blocks_when_recent_sns_notification_exists(self) -> None:
        repo = type(
            "Repo",
            (),
            {
                "list_recent": lambda self, ticker, limit=100: [
                    DummyRecentLog(category="SNS注目", sent_at="2026-02-19T11:30:00+00:00")
                ]
            },
        )()
        gate = run_intelligence_job._create_grok_fetch_gate(notification_log_repo=repo, cooldown_hours=3)
        item = type("Item", (), {"ticker": "3901:TSE"})()

        result = gate(item, "2026-02-19T12:00:00+00:00")

        self.assertFalse(result)


if __name__ == "__main__":
    import unittest

    unittest.main()

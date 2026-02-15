from __future__ import annotations

import io
import json
from dataclasses import dataclass
from unittest import TestCase
from unittest.mock import patch

import scripts.run_intelligence_job as run_intelligence_job
from kabu_per_bot.pipeline import PipelineResult
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


class RunIntelligenceJobScriptTest(TestCase):
    def test_main_stdout_outputs_summary_json(self) -> None:
        args = run_intelligence_job.argparse.Namespace(
            now_iso="2026-02-12T09:00:00+00:00",
            execution_mode="all",
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


if __name__ == "__main__":
    import unittest

    unittest.main()

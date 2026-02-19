from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from unittest import TestCase
from unittest.mock import patch

import scripts.run_immediate_window_job as run_immediate_window_job
from kabu_per_bot.settings import AppSettings


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

    def stream(self):
        prefix = f"{self.path}/"
        return [
            FakeSnapshot(exists=True, data=dict(value))
            for key, value in self.db.items()
            if key.startswith(prefix)
        ]


@dataclass
class FakeFirestoreClient:
    db: dict[str, dict] = field(default_factory=dict)

    def collection(self, name: str) -> FakeCollectionRef:
        return FakeCollectionRef(path=name, db=self.db)


class RunImmediateWindowJobTest(TestCase):
    def test_main_skips_when_outside_window(self) -> None:
        client = FakeFirestoreClient()
        args = run_immediate_window_job.argparse.Namespace(
            trade_date="2026-02-19",
            window="open",
            now_iso="2026-02-19T12:00:00+09:00",
            discord_webhook_url="",
            jquants_api_key="",
            stdout=True,
            no_notification_log=False,
        )
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=2,
            window_3m_days=2,
            window_1y_days=2,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=False,
            x_api_bearer_token="",
        )

        with (
            patch.object(run_immediate_window_job, "parse_args", return_value=args),
            patch.object(run_immediate_window_job, "load_settings", return_value=settings),
            patch.object(run_immediate_window_job, "_create_firestore_client", return_value=client),
            patch.object(run_immediate_window_job, "run_daily_pipeline") as mocked_pipeline,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_immediate_window_job.main()

        self.assertEqual(code, 0)
        mocked_pipeline.assert_not_called()
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        summary = json.loads(lines[-1])
        self.assertEqual(summary, {"processed": 0, "sent": 0, "skipped": 0, "errors": 0})

    def test_main_runs_pipeline_when_window_matches(self) -> None:
        client = FakeFirestoreClient(
            db={
                "global_settings/runtime": {
                    "cooldown_hours": 5,
                }
            }
        )
        args = run_immediate_window_job.argparse.Namespace(
            trade_date="2026-02-19",
            window="open",
            now_iso="2026-02-19T09:30:00+09:00",
            discord_webhook_url="",
            jquants_api_key="",
            stdout=True,
            no_notification_log=False,
        )
        settings = AppSettings(
            app_env="test",
            timezone="Asia/Tokyo",
            window_1w_days=2,
            window_3m_days=2,
            window_1y_days=2,
            cooldown_hours=2,
            firestore_project_id="",
            ai_notifications_enabled=False,
            x_api_bearer_token="",
        )
        pipeline_result = run_immediate_window_job.PipelineResult(
            processed_tickers=1,
            sent_notifications=1,
            skipped_notifications=0,
            errors=0,
        )

        with (
            patch.object(run_immediate_window_job, "parse_args", return_value=args),
            patch.object(run_immediate_window_job, "load_settings", return_value=settings),
            patch.object(run_immediate_window_job, "_create_firestore_client", return_value=client),
            patch.object(run_immediate_window_job, "create_default_market_data_source", return_value=object()),
            patch.object(run_immediate_window_job, "run_daily_pipeline", return_value=pipeline_result) as mocked_pipeline,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_immediate_window_job.main()

        self.assertEqual(code, 0)
        self.assertEqual(mocked_pipeline.call_count, 1)
        config = mocked_pipeline.call_args.kwargs["config"]
        self.assertEqual(config.cooldown_hours, 5)
        self.assertEqual(config.execution_mode.value, "DAILY")
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        summary = json.loads(lines[-1])
        self.assertEqual(summary, {"processed": 1, "sent": 1, "skipped": 0, "errors": 0})


if __name__ == "__main__":
    import unittest

    unittest.main()

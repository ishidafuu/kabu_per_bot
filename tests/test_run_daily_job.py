from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from unittest import TestCase
from unittest.mock import patch

import scripts.run_daily_job as run_daily_job
from kabu_per_bot.market_data import MarketDataSnapshot
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
        _ = merge
        self.db[self.path] = dict(data)

    def get(self) -> FakeSnapshot:
        if self.path not in self.db:
            return FakeSnapshot(exists=False, data=None)
        return FakeSnapshot(exists=True, data=dict(self.db[self.path]))

    def create(self, data: dict) -> None:
        if self.path in self.db:
            raise RuntimeError("already exists")
        self.db[self.path] = dict(data)

    def delete(self) -> None:
        if self.path in self.db:
            del self.db[self.path]


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


class StaticMarketDataSource:
    @property
    def source_name(self) -> str:
        return "fake"

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        _ = ticker
        return MarketDataSnapshot.create(
            ticker="3901:TSE",
            close_price=100.0,
            eps_forecast=10.0,
            sales_forecast=100.0,
            source="株探",
            earnings_date="2026-05-10",
        )


class RunDailyJobTest(TestCase):
    def test_main_persists_firestore_and_outputs_summary_json(self) -> None:
        client = FakeFirestoreClient(
            db={
                "watchlist/3901:TSE": {
                    "ticker": "3901:TSE",
                    "name": "富士フイルム",
                    "metric_type": "PER",
                    "notify_channel": "DISCORD",
                    "notify_timing": "IMMEDIATE",
                    "ai_enabled": False,
                    "is_active": True,
                    "created_at": "2026-02-11T00:00:00+00:00",
                    "updated_at": "2026-02-11T00:00:00+00:00",
                },
                "daily_metrics/3901:TSE|2026-02-11": {
                    "ticker": "3901:TSE",
                    "trade_date": "2026-02-11",
                    "close_price": 150.0,
                    "eps_forecast": 10.0,
                    "sales_forecast": 100.0,
                    "per_value": 15.0,
                    "psr_value": 1.5,
                    "data_source": "株探",
                    "fetched_at": "2026-02-11T00:00:00+00:00",
                },
            }
        )

        args = run_daily_job.argparse.Namespace(
            trade_date="2026-02-12",
            now_iso="2026-02-12T09:00:00+00:00",
            discord_webhook_url="",
            execution_mode="daily",
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
            patch.object(run_daily_job, "parse_args", return_value=args),
            patch.object(run_daily_job, "load_settings", return_value=settings),
            patch.object(run_daily_job, "_create_firestore_client", return_value=client),
            patch.object(run_daily_job, "create_default_market_data_source", return_value=StaticMarketDataSource()),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_daily_job.main()

        self.assertEqual(code, 0)
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        summary = json.loads(lines[-1])
        self.assertEqual(summary, {"processed": 1, "sent": 1, "skipped": 0, "errors": 0})

        self.assertIn("daily_metrics/3901:TSE|2026-02-12", client.db)
        self.assertIn("metric_medians/3901:TSE|2026-02-12", client.db)
        self.assertIn("signal_state/3901:TSE|2026-02-12", client.db)
        self.assertTrue(any(path.startswith("notification_log/") for path in client.db))

    def test_resolve_now_utc_iso_rejects_naive_datetime(self) -> None:
        with self.assertRaises(ValueError):
            run_daily_job.resolve_now_utc_iso(now_iso="2026-02-12T21:00:00")

    def test_resolve_trade_date_rejects_non_jst_timezone(self) -> None:
        with self.assertRaises(ValueError):
            run_daily_job.resolve_trade_date(now_iso="2026-02-12T09:00:00+00:00", timezone_name="UTC")

    def test_resolve_trade_date_accepts_explicit_trade_date_even_if_timezone_not_jst(self) -> None:
        trade_date = run_daily_job.resolve_trade_date(
            trade_date="2026-02-12",
            now_iso="2026-02-12T09:00:00+00:00",
            timezone_name="UTC",
        )
        self.assertEqual(trade_date, "2026-02-12")

    def test_main_raises_when_webhook_missing_without_stdout(self) -> None:
        args = run_daily_job.argparse.Namespace(
            trade_date="2026-02-12",
            now_iso="2026-02-12T09:00:00+00:00",
            discord_webhook_url="",
            execution_mode="daily",
            stdout=False,
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
            patch.object(run_daily_job, "parse_args", return_value=args),
            patch.object(run_daily_job, "load_settings", return_value=settings),
        ):
            with self.assertRaisesRegex(ValueError, "Discord webhook URL が必要です"):
                run_daily_job.main()

    def test_resolve_execution_mode(self) -> None:
        self.assertEqual(run_daily_job._resolve_execution_mode("daily").value, "DAILY")
        self.assertEqual(run_daily_job._resolve_execution_mode("at_21").value, "AT_21")
        self.assertEqual(run_daily_job._resolve_execution_mode("all").value, "ALL")

    def test_resolve_discord_webhook_default_prefers_daily_env(self) -> None:
        env = {
            run_daily_job.DISCORD_WEBHOOK_DAILY_ENV: "https://example.com/daily",
            run_daily_job.DISCORD_WEBHOOK_DEFAULT_ENV: "https://example.com/default",
        }
        with patch.dict(os.environ, env, clear=True):
            value = run_daily_job._resolve_discord_webhook_default(run_daily_job.DISCORD_WEBHOOK_DAILY_ENV)
        self.assertEqual(value, "https://example.com/daily")

    def test_resolve_discord_webhook_default_fallbacks_default_env(self) -> None:
        env = {
            run_daily_job.DISCORD_WEBHOOK_DEFAULT_ENV: "https://example.com/default",
        }
        with patch.dict(os.environ, env, clear=True):
            value = run_daily_job._resolve_discord_webhook_default(run_daily_job.DISCORD_WEBHOOK_DAILY_ENV)
        self.assertEqual(value, "https://example.com/default")

    def test_main_passes_execution_mode_to_pipeline_config(self) -> None:
        args = run_daily_job.argparse.Namespace(
            trade_date="2026-02-12",
            now_iso="2026-02-12T09:00:00+00:00",
            discord_webhook_url="",
            execution_mode="at_21",
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
            patch.object(run_daily_job, "parse_args", return_value=args),
            patch.object(run_daily_job, "load_settings", return_value=settings),
            patch.object(run_daily_job, "_create_firestore_client", return_value=FakeFirestoreClient()),
            patch.object(run_daily_job, "create_default_market_data_source", return_value=StaticMarketDataSource()),
            patch.object(run_daily_job, "run_daily_pipeline", return_value=run_daily_job.PipelineResult()) as mocked_pipeline,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            code = run_daily_job.main()

        self.assertEqual(code, 0)
        config = mocked_pipeline.call_args.kwargs["config"]
        self.assertEqual(config.channel, run_daily_job.DISCORD_DAILY_CHANNEL)
        self.assertEqual(config.execution_mode.value, "AT_21")

    def test_main_prefers_firestore_global_settings_for_cooldown(self) -> None:
        client = FakeFirestoreClient(
            db={
                "global_settings/runtime": {
                    "cooldown_hours": 5,
                    "updated_at": "2026-02-12T09:00:00+00:00",
                    "updated_by": "admin-user",
                }
            }
        )
        args = run_daily_job.argparse.Namespace(
            trade_date="2026-02-12",
            now_iso="2026-02-12T09:00:00+00:00",
            discord_webhook_url="",
            execution_mode="daily",
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
            patch.object(run_daily_job, "parse_args", return_value=args),
            patch.object(run_daily_job, "load_settings", return_value=settings),
            patch.object(run_daily_job, "_create_firestore_client", return_value=client),
            patch.object(run_daily_job, "create_default_market_data_source", return_value=StaticMarketDataSource()),
            patch.object(run_daily_job, "run_daily_pipeline", return_value=run_daily_job.PipelineResult()) as mocked_pipeline,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            code = run_daily_job.main()

        self.assertEqual(code, 0)
        config = mocked_pipeline.call_args.kwargs["config"]
        self.assertEqual(config.cooldown_hours, 5)

    def test_main_stdout_no_notification_log_does_not_persist_log(self) -> None:
        client = FakeFirestoreClient(
            db={
                "watchlist/3901:TSE": {
                    "ticker": "3901:TSE",
                    "name": "富士フイルム",
                    "metric_type": "PER",
                    "notify_channel": "DISCORD",
                    "notify_timing": "IMMEDIATE",
                    "ai_enabled": False,
                    "is_active": True,
                    "created_at": "2026-02-11T00:00:00+00:00",
                    "updated_at": "2026-02-11T00:00:00+00:00",
                },
                "daily_metrics/3901:TSE|2026-02-11": {
                    "ticker": "3901:TSE",
                    "trade_date": "2026-02-11",
                    "close_price": 150.0,
                    "eps_forecast": 10.0,
                    "sales_forecast": 100.0,
                    "per_value": 15.0,
                    "psr_value": 1.5,
                    "data_source": "株探",
                    "fetched_at": "2026-02-11T00:00:00+00:00",
                },
            }
        )
        args = run_daily_job.argparse.Namespace(
            trade_date="2026-02-12",
            now_iso="2026-02-12T09:00:00+00:00",
            discord_webhook_url="",
            execution_mode="daily",
            stdout=True,
            no_notification_log=True,
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
            patch.object(run_daily_job, "parse_args", return_value=args),
            patch.object(run_daily_job, "load_settings", return_value=settings),
            patch.object(run_daily_job, "_create_firestore_client", return_value=client),
            patch.object(run_daily_job, "create_default_market_data_source", return_value=StaticMarketDataSource()),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_daily_job.main()

        self.assertEqual(code, 0)
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        summary = json.loads(lines[-1])
        self.assertEqual(summary, {"processed": 1, "sent": 1, "skipped": 0, "errors": 0})
        self.assertFalse(any(path.startswith("notification_log/") for path in client.db))

    def test_main_no_notification_log_requires_stdout(self) -> None:
        args = run_daily_job.argparse.Namespace(
            trade_date="2026-02-12",
            now_iso="2026-02-12T09:00:00+00:00",
            discord_webhook_url="https://example.com/webhook",
            execution_mode="daily",
            stdout=False,
            no_notification_log=True,
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
            patch.object(run_daily_job, "parse_args", return_value=args),
            patch.object(run_daily_job, "load_settings", return_value=settings),
            patch.object(run_daily_job, "_create_firestore_client", return_value=FakeFirestoreClient()),
        ):
            with self.assertRaisesRegex(ValueError, "--no-notification-log は --stdout と併用してください"):
                run_daily_job.main()


if __name__ == "__main__":
    import unittest

    unittest.main()

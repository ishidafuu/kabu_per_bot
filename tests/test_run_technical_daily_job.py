from __future__ import annotations

from dataclasses import dataclass
import json
import os
import unittest
from unittest.mock import patch

import scripts.run_technical_daily_job as target
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings
from kabu_per_bot.technical_job import TechnicalJobResult, TechnicalTickerJobResult
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


@dataclass
class DummyWatchlistRepo:
    items: list[WatchlistItem] | None = None

    def list_all(self):
        return list(self.items or [])


class DummyNotificationLogRepo:
    def __init__(self) -> None:
        self.job_runs: list[dict[str, object]] = []

    def append_job_run(
        self,
        *,
        job_name: str,
        started_at: str,
        finished_at: str,
        status: str,
        error_count: int = 0,
        detail: str | None = None,
    ) -> None:
        self.job_runs.append(
            {
                "job_name": job_name,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": status,
                "error_count": error_count,
                "detail": detail,
            }
        )


def _settings():
    return type(
        "Settings",
        (),
        {
            "firestore_project_id": "demo-project",
            "timezone": "Asia/Tokyo",
            "cooldown_hours": 2,
        },
    )()


def _watch_item(ticker: str) -> WatchlistItem:
    return WatchlistItem(
        ticker=ticker,
        name="富士フイルム",
        metric_type=MetricType.PER,
        notify_channel=NotifyChannel.DISCORD,
        notify_timing=NotifyTiming.IMMEDIATE,
    )


class TechnicalDailyJobScriptTest(unittest.TestCase):
    def test_resolve_discord_webhook_default_prefers_technical_env(self) -> None:
        env = {
            target.DISCORD_WEBHOOK_TECHNICAL_ENV: "https://example.com/technical",
            target.DISCORD_WEBHOOK_DAILY_ENV: "https://example.com/daily",
            target.DISCORD_WEBHOOK_DEFAULT_ENV: "https://example.com/default",
        }
        with patch.dict(os.environ, env, clear=True):
            value = target._resolve_discord_webhook_default(
                target.DISCORD_WEBHOOK_TECHNICAL_ENV,
                target.DISCORD_WEBHOOK_DAILY_ENV,
            )
        self.assertEqual(value, "https://example.com/technical")

    def test_resolve_discord_webhook_default_fallbacks_daily_then_default(self) -> None:
        with patch.dict(
            os.environ,
            {
                target.DISCORD_WEBHOOK_DAILY_ENV: "https://example.com/daily",
                target.DISCORD_WEBHOOK_DEFAULT_ENV: "https://example.com/default",
            },
            clear=True,
        ):
            value = target._resolve_discord_webhook_default(
                target.DISCORD_WEBHOOK_TECHNICAL_ENV,
                target.DISCORD_WEBHOOK_DAILY_ENV,
            )
        self.assertEqual(value, "https://example.com/daily")

        with patch.dict(
            os.environ,
            {
                target.DISCORD_WEBHOOK_DEFAULT_ENV: "https://example.com/default",
            },
            clear=True,
        ):
            value = target._resolve_discord_webhook_default(
                target.DISCORD_WEBHOOK_TECHNICAL_ENV,
                target.DISCORD_WEBHOOK_DAILY_ENV,
            )
        self.assertEqual(value, "https://example.com/default")

    def test_main_runs_job_and_records_job_run(self) -> None:
        args = target.argparse.Namespace(
            to_date="2026-03-08",
            now_iso="2026-03-08T18:00:00+09:00",
            tickers="3901:TSE",
            api_key="dummy",
            discord_webhook_url="https://example.com/webhook",
            execution_mode="daily",
            stdout=True,
            no_notification_log=True,
            skip_alerts=False,
            full_refresh=False,
            initial_lookback_days=760,
            overlap_days=30,
        )
        notification_log_repo = DummyNotificationLogRepo()
        result = TechnicalJobResult(
            to_date="2026-03-08",
            full_refresh=False,
            alerts_enabled=True,
            processed_tickers=1,
            fetched_rows=3,
            upserted_rows=3,
            indicator_written_rows=2,
            sent_notifications=1,
            skipped_notifications=0,
            errors=0,
            tickers=(
                TechnicalTickerJobResult(
                    ticker="3901:TSE",
                    from_date="2026-02-05",
                    to_date="2026-03-08",
                    fetched_rows=3,
                    upserted_rows=3,
                    indicator_read_rows=20,
                    indicator_written_rows=2,
                    latest_fetched_trade_date="2026-03-08",
                    latest_calculated_trade_date="2026-03-08",
                ),
            ),
        )

        with (
            patch.object(target, "parse_args", return_value=args),
            patch.object(target, "load_settings", return_value=_settings()),
            patch.object(target, "_create_firestore_client", return_value=object()),
            patch.object(target, "_resolve_runtime_settings", return_value=GlobalRuntimeSettings()),
            patch.object(target, "FirestoreWatchlistRepository", return_value=DummyWatchlistRepo(items=[_watch_item("3901:TSE")])),
            patch.object(target, "FirestorePriceBarsDailyRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalIndicatorsDailyRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalSyncStateRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalAlertRulesRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalAlertStateRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalProfilesRepository", return_value=object()),
            patch.object(target, "FirestoreNotificationLogRepository", return_value=notification_log_repo),
            patch.object(target, "JQuantsV2Client", return_value=object()),
            patch.object(target, "run_technical_job", return_value=result) as mocked_run,
            patch("builtins.print") as mocked_print,
        ):
            code = target.main()

        self.assertEqual(code, 0)
        self.assertEqual(mocked_run.call_args.kwargs["full_refresh"], False)
        self.assertTrue(mocked_run.call_args.kwargs["alerts_enabled"])
        self.assertEqual(notification_log_repo.job_runs[0]["job_name"], "technical_daily")
        self.assertEqual(notification_log_repo.job_runs[0]["status"], "SUCCESS")
        payload = json.loads(mocked_print.call_args.args[0])
        self.assertEqual(payload["sent_notifications"], 1)

    def test_main_honors_skip_alerts_and_full_refresh(self) -> None:
        args = target.argparse.Namespace(
            to_date="2026-03-08",
            now_iso="2026-03-08T18:00:00+09:00",
            tickers="",
            api_key="dummy",
            discord_webhook_url="https://example.com/webhook",
            execution_mode="daily",
            stdout=True,
            no_notification_log=False,
            skip_alerts=True,
            full_refresh=True,
            initial_lookback_days=760,
            overlap_days=30,
        )
        notification_log_repo = DummyNotificationLogRepo()

        with (
            patch.object(target, "parse_args", return_value=args),
            patch.object(target, "load_settings", return_value=_settings()),
            patch.object(target, "_create_firestore_client", return_value=object()),
            patch.object(target, "_resolve_runtime_settings", return_value=GlobalRuntimeSettings()),
            patch.object(target, "FirestoreWatchlistRepository", return_value=DummyWatchlistRepo()),
            patch.object(target, "FirestorePriceBarsDailyRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalIndicatorsDailyRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalSyncStateRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalAlertRulesRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalAlertStateRepository", return_value=object()),
            patch.object(target, "FirestoreTechnicalProfilesRepository", return_value=object()),
            patch.object(target, "FirestoreNotificationLogRepository", return_value=notification_log_repo),
            patch.object(target, "JQuantsV2Client", return_value=object()),
            patch.object(target, "run_technical_job", return_value=TechnicalJobResult(
                to_date="2026-03-08",
                full_refresh=True,
                alerts_enabled=False,
                processed_tickers=0,
                fetched_rows=0,
                upserted_rows=0,
                indicator_written_rows=0,
                sent_notifications=0,
                skipped_notifications=0,
                errors=0,
                tickers=(),
            )) as mocked_run,
            patch("builtins.print"),
        ):
            code = target.main()

        self.assertEqual(code, 0)
        self.assertTrue(mocked_run.call_args.kwargs["full_refresh"])
        self.assertFalse(mocked_run.call_args.kwargs["alerts_enabled"])

    def test_resolve_sender_requires_technical_or_fallback_webhook(self) -> None:
        args = target.argparse.Namespace(stdout=False, discord_webhook_url="")

        with self.assertRaisesRegex(ValueError, "DISCORD_WEBHOOK_URL_TECHNICAL"):
            target._resolve_sender(args)


if __name__ == "__main__":
    unittest.main()

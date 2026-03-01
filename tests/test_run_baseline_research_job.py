from __future__ import annotations

import io
import json
from unittest import TestCase
from unittest.mock import MagicMock, patch

import scripts.run_baseline_research_job as run_baseline_research_job
from kabu_per_bot.baseline_research import BaselineRefreshResult
from kabu_per_bot.settings import AppSettings
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchPriority, WatchlistItem


def _settings() -> AppSettings:
    return AppSettings(
        app_env="test",
        timezone="Asia/Tokyo",
        window_1w_days=5,
        window_3m_days=63,
        window_1y_days=252,
        cooldown_hours=2,
        firestore_project_id="",
        ai_notifications_enabled=False,
        x_api_bearer_token="",
    )


def _watchlist_item(ticker: str) -> WatchlistItem:
    return WatchlistItem(
        ticker=ticker,
        name="テスト銘柄",
        metric_type=MetricType.PER,
        notify_channel=NotifyChannel.DISCORD,
        notify_timing=NotifyTiming.IMMEDIATE,
        priority=WatchPriority.MEDIUM,
        is_active=True,
        evaluation_enabled=True,
    )


class RunBaselineResearchJobTest(TestCase):
    def test_resolve_trade_date_validates_explicit_input(self) -> None:
        with self.assertRaises(ValueError):
            run_baseline_research_job._resolve_trade_date(trade_date="2026-13-01", now_iso=None)

    def test_should_run_monthly_now(self) -> None:
        self.assertTrue(
            run_baseline_research_job._should_run_monthly_now(
                now_iso="2026-03-01T09:00:00+00:00",
                scheduled_time="18:00",
            )
        )
        self.assertFalse(
            run_baseline_research_job._should_run_monthly_now(
                now_iso="2026-03-02T09:00:00+00:00",
                scheduled_time="18:00",
            )
        )

    def test_main_skips_when_not_monthly_scheduled_time(self) -> None:
        args = run_baseline_research_job.argparse.Namespace(
            now_iso="2026-03-02T09:00:00+00:00",
            trade_date=None,
            tickers=(),
            discord_webhook_url="",
            stdout=True,
            jquants_api_key="",
            ignore_baseline_schedule=False,
        )

        with (
            patch.object(run_baseline_research_job, "parse_args", return_value=args),
            patch.object(run_baseline_research_job, "load_settings", return_value=_settings()),
            patch.object(run_baseline_research_job, "_create_firestore_client", return_value=object()),
            patch.object(run_baseline_research_job, "_resolve_sender", return_value=MagicMock()),
            patch.object(run_baseline_research_job, "_resolve_runtime_baseline_scheduled_time", return_value="18:00"),
            patch.object(run_baseline_research_job, "refresh_baseline_research") as mocked_refresh,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_baseline_research_job.main()

        self.assertEqual(code, 0)
        mocked_refresh.assert_not_called()
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual(json.loads(lines[-1]), {"processed": 0, "updated": 0, "failed": 0})

    def test_main_runs_when_tickers_specified_even_if_off_schedule(self) -> None:
        args = run_baseline_research_job.argparse.Namespace(
            now_iso="2026-03-02T09:00:00+00:00",
            trade_date=None,
            tickers=("3901:TSE",),
            discord_webhook_url="",
            stdout=True,
            jquants_api_key="",
            ignore_baseline_schedule=False,
        )
        watchlist_repo = MagicMock()
        watchlist_repo.list_all.return_value = [_watchlist_item("3901:TSE")]
        baseline_repo = MagicMock()

        with (
            patch.object(run_baseline_research_job, "parse_args", return_value=args),
            patch.object(run_baseline_research_job, "load_settings", return_value=_settings()),
            patch.object(run_baseline_research_job, "_create_firestore_client", return_value=object()),
            patch.object(run_baseline_research_job, "_resolve_sender", return_value=MagicMock()),
            patch.object(run_baseline_research_job, "_resolve_runtime_baseline_scheduled_time", return_value="18:00"),
            patch.object(run_baseline_research_job, "FirestoreWatchlistRepository", return_value=watchlist_repo),
            patch.object(run_baseline_research_job, "FirestoreBaselineResearchRepository", return_value=baseline_repo),
            patch.object(run_baseline_research_job, "create_default_market_data_source", return_value=object()),
            patch.object(
                run_baseline_research_job,
                "refresh_baseline_research",
                return_value=BaselineRefreshResult(
                    processed_tickers=1,
                    updated_tickers=1,
                    failed_tickers=0,
                    failures=(),
                ),
            ) as mocked_refresh,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_baseline_research_job.main()

        self.assertEqual(code, 0)
        mocked_refresh.assert_called_once()
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual(json.loads(lines[-1]), {"processed": 1, "updated": 1, "failed": 0})

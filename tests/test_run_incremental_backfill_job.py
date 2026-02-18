from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from unittest import TestCase
from unittest.mock import patch

import scripts.run_incremental_backfill_job as run_incremental_backfill_job
from kabu_per_bot.backfill_service import BackfillExecutionResult
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


class RunIncrementalBackfillJobTest(TestCase):
    def test_main_uses_overlap_from_latest_trade_date(self) -> None:
        client = FakeFirestoreClient(
            db={
                "watchlist/3901:TSE": {
                    "ticker": "3901:TSE",
                    "name": "富士フイルム",
                    "metric_type": "PER",
                    "notify_channel": "DISCORD",
                    "notify_timing": "IMMEDIATE",
                    "is_active": True,
                    "created_at": "2026-02-11T00:00:00+00:00",
                    "updated_at": "2026-02-11T00:00:00+00:00",
                },
                "daily_metrics/3901:TSE|2026-02-10": {
                    "ticker": "3901:TSE",
                    "trade_date": "2026-02-10",
                    "close_price": 100,
                    "eps_forecast": 10,
                    "sales_forecast": 100,
                    "per_value": 10,
                    "psr_value": 1,
                    "data_source": "test",
                    "fetched_at": "2026-02-10T00:00:00+00:00",
                },
            }
        )
        args = run_incremental_backfill_job.argparse.Namespace(
            to_date="2026-02-12",
            tickers="",
            api_key="test-key",
            initial_lookback_days=400,
            overlap_days=3,
            dry_run=False,
        )
        settings = AppSettings(
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

        called_from_dates: list[str] = []

        def _fake_backfill(**kwargs):
            called_from_dates.append(kwargs["from_date"])
            return BackfillExecutionResult(
                ticker=kwargs["item"].ticker,
                from_date=kwargs["from_date"],
                to_date=kwargs["to_date"],
                generated=4,
                upserted=4,
            )

        with (
            patch.object(run_incremental_backfill_job, "parse_args", return_value=args),
            patch.object(run_incremental_backfill_job, "load_settings", return_value=settings),
            patch.object(run_incremental_backfill_job, "_create_firestore_client", return_value=client),
            patch.object(run_incremental_backfill_job, "JQuantsV2Client", return_value=object()),
            patch.object(run_incremental_backfill_job, "backfill_ticker_from_jquants", side_effect=_fake_backfill),
            patch.object(run_incremental_backfill_job, "refresh_latest_medians_and_signal", return_value=True),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_incremental_backfill_job.main()

        self.assertEqual(code, 0)
        self.assertEqual(called_from_dates, ["2026-02-07"])
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        summary = json.loads(lines[-1])
        self.assertEqual(summary["processed_tickers"], 1)
        self.assertEqual(summary["generated_rows"], 4)

    def test_main_uses_initial_lookback_when_history_missing(self) -> None:
        client = FakeFirestoreClient(
            db={
                "watchlist/3901:TSE": {
                    "ticker": "3901:TSE",
                    "name": "富士フイルム",
                    "metric_type": "PER",
                    "notify_channel": "DISCORD",
                    "notify_timing": "IMMEDIATE",
                    "is_active": True,
                    "created_at": "2026-02-11T00:00:00+00:00",
                    "updated_at": "2026-02-11T00:00:00+00:00",
                },
            }
        )
        args = run_incremental_backfill_job.argparse.Namespace(
            to_date="2026-02-12",
            tickers="",
            api_key="test-key",
            initial_lookback_days=400,
            overlap_days=7,
            dry_run=False,
        )
        settings = AppSettings(
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

        called_from_dates: list[str] = []

        def _fake_backfill(**kwargs):
            called_from_dates.append(kwargs["from_date"])
            return BackfillExecutionResult(
                ticker=kwargs["item"].ticker,
                from_date=kwargs["from_date"],
                to_date=kwargs["to_date"],
                generated=1,
                upserted=1,
            )

        with (
            patch.object(run_incremental_backfill_job, "parse_args", return_value=args),
            patch.object(run_incremental_backfill_job, "load_settings", return_value=settings),
            patch.object(run_incremental_backfill_job, "_create_firestore_client", return_value=client),
            patch.object(run_incremental_backfill_job, "JQuantsV2Client", return_value=object()),
            patch.object(run_incremental_backfill_job, "backfill_ticker_from_jquants", side_effect=_fake_backfill),
            patch.object(run_incremental_backfill_job, "refresh_latest_medians_and_signal", return_value=True),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            code = run_incremental_backfill_job.main()

        self.assertEqual(code, 0)
        self.assertEqual(called_from_dates, ["2025-01-08"])

    def test_main_prefers_bulk_latest_loader(self) -> None:
        client = FakeFirestoreClient(
            db={
                "watchlist/3901:TSE": {
                    "ticker": "3901:TSE",
                    "name": "富士フイルム",
                    "metric_type": "PER",
                    "notify_channel": "DISCORD",
                    "notify_timing": "IMMEDIATE",
                    "is_active": True,
                    "created_at": "2026-02-11T00:00:00+00:00",
                    "updated_at": "2026-02-11T00:00:00+00:00",
                },
            }
        )
        args = run_incremental_backfill_job.argparse.Namespace(
            to_date="2026-02-12",
            tickers="",
            api_key="test-key",
            initial_lookback_days=400,
            overlap_days=3,
            dry_run=False,
        )
        settings = AppSettings(
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

        class _BulkDailyRepo:
            def __init__(self) -> None:
                self.list_recent_calls = 0
                self.list_latest_calls = 0

            def list_recent(self, ticker: str, *, limit: int):
                _ = ticker, limit
                self.list_recent_calls += 1
                return []

            def list_latest_by_tickers(self, tickers: list[str]):
                from kabu_per_bot.metrics import DailyMetric

                self.list_latest_calls += 1
                return {
                    "3901:TSE": DailyMetric(
                        ticker="3901:TSE",
                        trade_date="2026-02-10",
                        close_price=100,
                        eps_forecast=10,
                        sales_forecast=100,
                        per_value=10,
                        psr_value=1,
                        data_source="test",
                        fetched_at="2026-02-10T00:00:00+00:00",
                    )
                }

            def upsert(self, metric):
                _ = metric

        bulk_repo = _BulkDailyRepo()

        called_from_dates: list[str] = []

        def _fake_backfill(**kwargs):
            called_from_dates.append(kwargs["from_date"])
            return BackfillExecutionResult(
                ticker=kwargs["item"].ticker,
                from_date=kwargs["from_date"],
                to_date=kwargs["to_date"],
                generated=1,
                upserted=1,
            )

        with (
            patch.object(run_incremental_backfill_job, "parse_args", return_value=args),
            patch.object(run_incremental_backfill_job, "load_settings", return_value=settings),
            patch.object(run_incremental_backfill_job, "_create_firestore_client", return_value=client),
            patch.object(run_incremental_backfill_job, "FirestoreDailyMetricsRepository", return_value=bulk_repo),
            patch.object(run_incremental_backfill_job, "FirestoreMetricMediansRepository", return_value=object()),
            patch.object(run_incremental_backfill_job, "FirestoreSignalStateRepository", return_value=object()),
            patch.object(run_incremental_backfill_job, "JQuantsV2Client", return_value=object()),
            patch.object(run_incremental_backfill_job, "backfill_ticker_from_jquants", side_effect=_fake_backfill),
            patch.object(run_incremental_backfill_job, "refresh_latest_medians_and_signal", return_value=True),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            code = run_incremental_backfill_job.main()

        self.assertEqual(code, 0)
        self.assertEqual(called_from_dates, ["2026-02-07"])
        self.assertEqual(bulk_repo.list_latest_calls, 1)
        self.assertEqual(bulk_repo.list_recent_calls, 0)


if __name__ == "__main__":
    import unittest

    unittest.main()

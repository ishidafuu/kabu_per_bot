from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from unittest import TestCase
from unittest.mock import patch

import scripts.run_technical_price_sync as run_technical_price_sync
from kabu_per_bot.settings import AppSettings
from kabu_per_bot.technical_sync import TechnicalPriceSyncResult


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
        del merge
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


class RunTechnicalPriceSyncTest(TestCase):
    def test_main_uses_overlap_from_latest_fetched_trade_date(self) -> None:
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
                "technical_sync_state/3901:TSE": {
                    "ticker": "3901:TSE",
                    "latest_fetched_trade_date": "2026-03-07",
                    "latest_calculated_trade_date": None,
                    "last_run_at": "2026-03-07T00:00:00+00:00",
                    "last_status": "SUCCESS",
                },
            }
        )
        args = run_technical_price_sync.argparse.Namespace(
            to_date="2026-03-08",
            tickers="",
            api_key="test-key",
            initial_lookback_days=760,
            overlap_days=30,
            full_refresh=False,
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

        def _fake_sync(**kwargs):
            called_from_dates.append(kwargs["from_date"])
            return TechnicalPriceSyncResult(
                ticker=kwargs["item"].ticker,
                from_date=kwargs["from_date"],
                to_date=kwargs["to_date"],
                fetched_rows=2,
                upserted_rows=2,
                latest_fetched_trade_date="2026-03-07",
                full_refresh=kwargs["full_refresh"],
            )

        with (
            patch.object(run_technical_price_sync, "parse_args", return_value=args),
            patch.object(run_technical_price_sync, "load_settings", return_value=settings),
            patch.object(run_technical_price_sync, "_create_firestore_client", return_value=client),
            patch.object(run_technical_price_sync, "JQuantsV2Client", return_value=object()),
            patch.object(run_technical_price_sync, "sync_ticker_price_bars", side_effect=_fake_sync),
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            code = run_technical_price_sync.main()

        self.assertEqual(code, 0)
        self.assertEqual(called_from_dates, ["2026-02-05"])
        lines = [line for line in stdout.getvalue().splitlines() if line.strip()]
        summary = json.loads(lines[-1])
        self.assertEqual(summary["processed_tickers"], 1)
        self.assertEqual(summary["fetched_rows"], 2)

    def test_main_uses_full_refresh_flag(self) -> None:
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
                "technical_sync_state/3901:TSE": {
                    "ticker": "3901:TSE",
                    "latest_fetched_trade_date": "2026-03-07",
                    "latest_calculated_trade_date": None,
                    "last_run_at": "2026-03-07T00:00:00+00:00",
                    "last_status": "SUCCESS",
                },
            }
        )
        args = run_technical_price_sync.argparse.Namespace(
            to_date="2026-03-08",
            tickers="",
            api_key="test-key",
            initial_lookback_days=760,
            overlap_days=30,
            full_refresh=True,
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

        def _fake_sync(**kwargs):
            called_from_dates.append(kwargs["from_date"])
            return TechnicalPriceSyncResult(
                ticker=kwargs["item"].ticker,
                from_date=kwargs["from_date"],
                to_date=kwargs["to_date"],
                fetched_rows=2,
                upserted_rows=2,
                latest_fetched_trade_date="2026-03-07",
                full_refresh=kwargs["full_refresh"],
            )

        with (
            patch.object(run_technical_price_sync, "parse_args", return_value=args),
            patch.object(run_technical_price_sync, "load_settings", return_value=settings),
            patch.object(run_technical_price_sync, "_create_firestore_client", return_value=client),
            patch.object(run_technical_price_sync, "JQuantsV2Client", return_value=object()),
            patch.object(run_technical_price_sync, "sync_ticker_price_bars", side_effect=_fake_sync),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            code = run_technical_price_sync.main()

        self.assertEqual(code, 0)
        self.assertEqual(called_from_dates, ["2024-02-07"])


if __name__ == "__main__":
    import unittest

    unittest.main()

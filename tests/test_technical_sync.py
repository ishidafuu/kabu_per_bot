from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.technical import PriceBarDaily, TechnicalSyncState
from kabu_per_bot.technical_sync import (
    build_price_bars_from_jquants_rows,
    resolve_technical_sync_from_date,
    sync_ticker_price_bars,
)
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


@dataclass
class FakeJQuantsClient:
    rows: list[dict]
    calls: list[dict] = field(default_factory=list)

    def get_eq_bars_daily(self, *, code_or_ticker: str, from_date: str, to_date: str) -> list[dict]:
        self.calls.append(
            {
                "code_or_ticker": code_or_ticker,
                "from_date": from_date,
                "to_date": to_date,
            }
        )
        return list(self.rows)


@dataclass
class InMemoryPriceBarsRepo:
    rows: list[PriceBarDaily] = field(default_factory=list)
    fail_on_trade_date: str | None = None

    def upsert(self, bar: PriceBarDaily) -> None:
        if self.fail_on_trade_date == bar.trade_date:
            raise RuntimeError(f"failed on {bar.trade_date}")
        self.rows = [row for row in self.rows if not (row.ticker == bar.ticker and row.trade_date == bar.trade_date)]
        self.rows.append(bar)


@dataclass
class InMemorySyncStateRepo:
    rows: dict[str, TechnicalSyncState] = field(default_factory=dict)

    def get(self, ticker: str) -> TechnicalSyncState | None:
        return self.rows.get(ticker)

    def upsert(self, state: TechnicalSyncState) -> None:
        self.rows[state.ticker] = state


def _watch_item() -> WatchlistItem:
    return WatchlistItem(
        ticker="3901:TSE",
        name="富士フイルム",
        metric_type=MetricType.PER,
        notify_channel=NotifyChannel.DISCORD,
        notify_timing=NotifyTiming.IMMEDIATE,
    )


class TechnicalSyncTest(unittest.TestCase):
    def test_resolve_technical_sync_from_date_initial_and_overlap(self) -> None:
        self.assertEqual(
            resolve_technical_sync_from_date(
                latest_fetched_trade_date=None,
                to_date="2026-03-08",
                initial_lookback_days=760,
                overlap_days=30,
            ),
            "2024-02-07",
        )
        self.assertEqual(
            resolve_technical_sync_from_date(
                latest_fetched_trade_date="2026-03-07",
                to_date="2026-03-08",
                initial_lookback_days=760,
                overlap_days=30,
            ),
            "2026-02-05",
        )

    def test_build_price_bars_from_jquants_rows(self) -> None:
        bars = build_price_bars_from_jquants_rows(
            ticker="3901:TSE",
            rows=[
                {
                    "Date": "20260307",
                    "Code": "39010",
                    "Open": "100",
                    "High": "105",
                    "Low": "99",
                    "Close": "104",
                    "Volume": "123456",
                    "TurnoverValue": "12500000",
                    "AdjustmentOpen": "100",
                    "AdjustmentHigh": "105",
                    "AdjustmentLow": "99",
                    "AdjustmentClose": "104",
                    "AdjustmentVolume": "123456",
                }
            ],
            fetched_at="2026-03-08T00:00:00+00:00",
        )

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].code, "3901")
        self.assertEqual(bars[0].trade_date, "2026-03-07")
        self.assertEqual(bars[0].adj_close, 104.0)

    def test_sync_ticker_price_bars_updates_state(self) -> None:
        client = FakeJQuantsClient(
            rows=[
                {
                    "Date": "20260306",
                    "Code": "39010",
                    "Open": "100",
                    "High": "102",
                    "Low": "98",
                    "Close": "101",
                    "Volume": "1000",
                    "TurnoverValue": "100000",
                    "AdjustmentOpen": "100",
                    "AdjustmentHigh": "102",
                    "AdjustmentLow": "98",
                    "AdjustmentClose": "101",
                    "AdjustmentVolume": "1000",
                },
                {
                    "Date": "20260307",
                    "Code": "39010",
                    "Open": "101",
                    "High": "105",
                    "Low": "100",
                    "Close": "104",
                    "Volume": "2000",
                    "TurnoverValue": "200000",
                    "AdjustmentOpen": "101",
                    "AdjustmentHigh": "105",
                    "AdjustmentLow": "100",
                    "AdjustmentClose": "104",
                    "AdjustmentVolume": "2000",
                },
            ]
        )
        price_repo = InMemoryPriceBarsRepo()
        sync_repo = InMemorySyncStateRepo()

        result = sync_ticker_price_bars(
            item=_watch_item(),
            from_date="2026-02-05",
            to_date="2026-03-08",
            jquants_client=client,
            price_bars_repo=price_repo,
            sync_state_repo=sync_repo,
            fetched_at="2026-03-08T00:00:00+00:00",
        )

        self.assertEqual(result.fetched_rows, 2)
        self.assertEqual(result.upserted_rows, 2)
        self.assertEqual(result.latest_fetched_trade_date, "2026-03-07")
        self.assertEqual(sync_repo.rows["3901:TSE"].latest_fetched_trade_date, "2026-03-07")
        self.assertEqual(sync_repo.rows["3901:TSE"].last_status, "SUCCESS")

    def test_sync_failure_does_not_advance_state(self) -> None:
        client = FakeJQuantsClient(
            rows=[
                {
                    "Date": "20260307",
                    "Code": "39010",
                    "Open": "101",
                    "High": "105",
                    "Low": "100",
                    "Close": "104",
                    "Volume": "2000",
                    "TurnoverValue": "200000",
                    "AdjustmentOpen": "101",
                    "AdjustmentHigh": "105",
                    "AdjustmentLow": "100",
                    "AdjustmentClose": "104",
                    "AdjustmentVolume": "2000",
                }
            ]
        )
        price_repo = InMemoryPriceBarsRepo(fail_on_trade_date="2026-03-07")
        sync_repo = InMemorySyncStateRepo(
            rows={
                "3901:TSE": TechnicalSyncState(
                    ticker="3901:TSE",
                    latest_fetched_trade_date="2026-03-06",
                    latest_calculated_trade_date=None,
                    last_run_at="2026-03-07T00:00:00+00:00",
                    last_status="SUCCESS",
                )
            }
        )

        with self.assertRaises(RuntimeError):
            sync_ticker_price_bars(
                item=_watch_item(),
                from_date="2026-02-05",
                to_date="2026-03-08",
                jquants_client=client,
                price_bars_repo=price_repo,
                sync_state_repo=sync_repo,
                fetched_at="2026-03-08T00:00:00+00:00",
            )

        self.assertEqual(sync_repo.rows["3901:TSE"].latest_fetched_trade_date, "2026-03-06")
        self.assertEqual(sync_repo.rows["3901:TSE"].last_status, "ERROR")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import unittest

from kabu_per_bot.technical import PriceBarDaily, TechnicalIndicatorsDaily, TechnicalSyncState
from kabu_per_bot.technical_indicators import (
    TECHNICAL_INDICATOR_SCHEMA_VERSION,
    calculate_technical_indicators_for_bars,
    recalculate_recent_technical_indicators,
)


def _bar(
    *,
    trade_date: str,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
    adj_open: float | None = None,
    adj_high: float | None = None,
    adj_low: float | None = None,
    adj_close: float | None = None,
    volume: int = 200_000,
    turnover_value: float = 120_000_000,
) -> PriceBarDaily:
    return PriceBarDaily(
        ticker="3901:TSE",
        trade_date=trade_date,
        code="3901",
        date=trade_date,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
        turnover_value=turnover_value,
        adj_open=adj_open if adj_open is not None else open_price,
        adj_high=adj_high if adj_high is not None else high_price,
        adj_low=adj_low if adj_low is not None else low_price,
        adj_close=adj_close if adj_close is not None else close_price,
        adj_volume=float(volume),
        source="J-Quants LITE",
        fetched_at="2026-03-08T00:00:00+00:00",
    )


@dataclass
class InMemoryPriceBarRepo:
    rows: list[PriceBarDaily]

    def list_recent(self, ticker: str, *, limit: int) -> list[PriceBarDaily]:
        matched = [row for row in self.rows if row.ticker == ticker]
        matched.sort(key=lambda row: row.trade_date, reverse=True)
        return matched[:limit]


@dataclass
class InMemoryIndicatorsRepo:
    rows: list[TechnicalIndicatorsDaily] = field(default_factory=list)

    def upsert(self, indicators: TechnicalIndicatorsDaily) -> None:
        self.rows = [
            row
            for row in self.rows
            if not (row.ticker == indicators.ticker and row.trade_date == indicators.trade_date)
        ]
        self.rows.append(indicators)


@dataclass
class InMemorySyncStateRepo:
    rows: dict[str, TechnicalSyncState] = field(default_factory=dict)

    def get(self, ticker: str) -> TechnicalSyncState | None:
        return self.rows.get(ticker)

    def upsert(self, state: TechnicalSyncState) -> None:
        self.rows[state.ticker] = state


class TechnicalIndicatorsTest(unittest.TestCase):
    def test_calculate_handles_high_equals_low_exception_rules(self) -> None:
        rows = calculate_technical_indicators_for_bars(
            ticker="3901:TSE",
            bars=[
                _bar(
                    trade_date="2026-03-07",
                    open_price=100.0,
                    high_price=100.0,
                    low_price=100.0,
                    close_price=100.0,
                )
            ],
            calculated_at="2026-03-08T00:00:00+00:00",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get_value("body_ratio"), 0.0)
        self.assertEqual(rows[0].get_value("close_position_in_range"), 0.5)
        self.assertEqual(rows[0].get_value("upper_shadow_ratio"), 0.0)
        self.assertEqual(rows[0].get_value("lower_shadow_ratio"), 0.0)
        self.assertEqual(rows[0].get_value("candle_type"), "flat_bar")

    def test_calculate_returns_null_and_false_on_insufficient_history(self) -> None:
        rows = calculate_technical_indicators_for_bars(
            ticker="3901:TSE",
            bars=[
                _bar(
                    trade_date="2026-03-07",
                    open_price=100.0,
                    high_price=105.0,
                    low_price=99.0,
                    close_price=104.0,
                )
            ],
            calculated_at="2026-03-08T00:00:00+00:00",
        )

        latest = rows[-1]
        self.assertIsNone(latest.get_value("ma_200"))
        self.assertIsNone(latest.get_value("high_52w"))
        self.assertFalse(latest.get_value("above_ma200"))
        self.assertFalse(latest.get_value("cross_up_ma200"))
        self.assertIsNone(latest.get_value("volatility_20d"))

    def test_calculate_long_term_indicators(self) -> None:
        bars = []
        start_day = date(2025, 1, 1)
        for index in range(1, 261):
            adj_close = float(100 + index)
            bars.append(
                _bar(
                    trade_date=(start_day + timedelta(days=index - 1)).isoformat(),
                    open_price=adj_close - 1,
                    high_price=adj_close + 2,
                    low_price=adj_close - 2,
                    close_price=adj_close,
                    adj_open=adj_close - 1,
                    adj_high=adj_close + 2,
                    adj_low=adj_close - 2,
                    adj_close=adj_close,
                    volume=300_000 + index,
                    turnover_value=150_000_000 + index * 100_000,
                )
            )
        rows = calculate_technical_indicators_for_bars(
            ticker="3901:TSE",
            bars=bars,
            calculated_at="2026-03-08T00:00:00+00:00",
        )
        latest = rows[-1]

        self.assertEqual(latest.schema_version, TECHNICAL_INDICATOR_SCHEMA_VERSION)
        self.assertIsNotNone(latest.get_value("ma_200"))
        self.assertIsNotNone(latest.get_value("high_52w"))
        self.assertIsNotNone(latest.get_value("atr_14"))
        self.assertIsNotNone(latest.get_value("volatility_20d"))
        self.assertTrue(latest.get_value("above_ma200"))

    def test_recalculate_recent_technical_indicators_reads_520_and_writes_260(self) -> None:
        bars = []
        start_day = date(2025, 1, 1)
        for index in range(1, 401):
            bars.append(
                _bar(
                    trade_date=(start_day + timedelta(days=index - 1)).isoformat(),
                    open_price=float(100 + index),
                    high_price=float(102 + index),
                    low_price=float(99 + index),
                    close_price=float(101 + index),
                    volume=200_000 + index,
                    turnover_value=130_000_000 + index * 50_000,
                )
            )
        price_repo = InMemoryPriceBarRepo(rows=bars)
        indicators_repo = InMemoryIndicatorsRepo()
        sync_repo = InMemorySyncStateRepo(
            rows={
                "3901:TSE": TechnicalSyncState(
                    ticker="3901:TSE",
                    latest_fetched_trade_date=bars[-1].trade_date,
                    latest_calculated_trade_date=None,
                    last_run_at="2026-03-07T00:00:00+00:00",
                    last_status="SUCCESS",
                )
            }
        )

        result = recalculate_recent_technical_indicators(
            ticker="3901:TSE",
            price_bars_repo=price_repo,
            indicators_repo=indicators_repo,
            sync_state_repo=sync_repo,
            read_limit=520,
            write_limit=260,
            calculated_at="2026-03-08T00:00:00+00:00",
        )

        self.assertEqual(result.read_rows, 400)
        self.assertEqual(result.written_rows, 260)
        self.assertEqual(sync_repo.rows["3901:TSE"].latest_calculated_trade_date, result.latest_calculated_trade_date)
        self.assertEqual(sync_repo.rows["3901:TSE"].last_status, "CALCULATED")


if __name__ == "__main__":
    unittest.main()

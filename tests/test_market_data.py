from __future__ import annotations

import unittest

from kabu_per_bot.market_data import (
    FallbackMarketDataSource,
    MarketDataFetchError,
    MarketDataSnapshot,
    MarketDataSource,
    MarketDataUnavailableError,
)


class StaticSource(MarketDataSource):
    def __init__(self, source_name: str, close_price: float) -> None:
        self._source_name = source_name
        self.close_price = close_price

    @property
    def source_name(self) -> str:
        return self._source_name

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        return MarketDataSnapshot.create(
            ticker=ticker,
            close_price=self.close_price,
            eps_forecast=10.0,
            sales_forecast=100.0,
            source=self.source_name,
            earnings_date="2026-05-10",
        )


class FailingSource(MarketDataSource):
    def __init__(self, source_name: str, reason: str) -> None:
        self._source_name = source_name
        self.reason = reason

    @property
    def source_name(self) -> str:
        return self._source_name

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        raise MarketDataFetchError(source=self.source_name, ticker=ticker, reason=self.reason)


class MarketDataSourceTest(unittest.TestCase):
    def test_fallback_uses_next_source(self) -> None:
        provider = FallbackMarketDataSource(
            [
                FailingSource(source_name="四季報online", reason="timeout"),
                StaticSource(source_name="株探", close_price=100.0),
            ]
        )
        snapshot = provider.fetch_snapshot("3901:tse")
        self.assertEqual(snapshot.source, "株探")
        self.assertEqual(snapshot.ticker, "3901:TSE")
        self.assertEqual(snapshot.close_price, 100.0)

    def test_fallback_raises_when_all_sources_fail(self) -> None:
        provider = FallbackMarketDataSource(
            [
                FailingSource(source_name="四季報online", reason="401"),
                FailingSource(source_name="株探", reason="404"),
                FailingSource(source_name="Yahoo!ファイナンス", reason="500"),
            ]
        )
        with self.assertRaises(MarketDataUnavailableError) as ctx:
            provider.fetch_snapshot("3901:TSE")
        self.assertIn("四季報online", str(ctx.exception))
        self.assertIn("Yahoo!ファイナンス", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from kabu_per_bot.market_data import (
    FallbackMarketDataSource,
    KabutanMarketDataSource,
    MarketDataFetchError,
    MarketDataSnapshot,
    MarketDataSource,
    MarketDataUnavailableError,
    YahooFinanceMarketDataSource,
    create_default_market_data_source,
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


class CrashingSource(MarketDataSource):
    @property
    def source_name(self) -> str:
        return "crash"

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        raise RuntimeError("unexpected")


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class FakeHttpClient:
    def __init__(self, routes: dict[str, FakeResponse | Exception]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> FakeResponse:
        del timeout
        self.calls.append(url)
        route = self.routes.get(url)
        if route is None:
            return FakeResponse(404, "")
        if isinstance(route, Exception):
            raise route
        return route

    def close(self) -> None:
        return None


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

    def test_fallback_wraps_unexpected_error(self) -> None:
        provider = FallbackMarketDataSource([CrashingSource()])
        with self.assertRaises(MarketDataUnavailableError) as ctx:
            provider.fetch_snapshot("3901:TSE")
        self.assertIn("crash failed", str(ctx.exception))

    def test_default_source_order_is_fixed(self) -> None:
        provider = create_default_market_data_source(
            shikiho_client=FakeHttpClient({}),
            kabutan_client=FakeHttpClient({}),
            yahoo_client=FakeHttpClient({}),
        )
        self.assertEqual([source.source_name for source in provider._sources], ["四季報online", "株探", "Yahoo!ファイナンス"])

    def test_kabutan_source_parses_snapshot(self) -> None:
        stock_url = "https://kabutan.jp/stock/?code=7203"
        finance_url = "https://kabutan.jp/stock/finance?code=7203"
        stock_html = """
        <table>
          <tr><th scope='row'>終値</th><td>3,705</td></tr>
        </table>
        """
        finance_html = """
        <table>
          <tr>
            <th scope='row'><span class='kubun1'>I 予 </span>2026.03</th>
            <td>50,000,000</td>
            <td>3,800,000</td>
            <td>5,020,000</td>
            <td>3,570,000</td>
            <td>273.9</td>
            <td>95</td>
            <td class='fb_pdf1'>26/02/06</td>
          </tr>
        </table>
        """
        client = FakeHttpClient(
            {
                stock_url: FakeResponse(200, stock_html),
                finance_url: FakeResponse(200, finance_html),
            }
        )
        source = KabutanMarketDataSource(http_client=client)
        snapshot = source.fetch_snapshot("7203:TSE")

        self.assertEqual(snapshot.source, "株探")
        self.assertEqual(snapshot.close_price, 3705.0)
        self.assertEqual(snapshot.eps_forecast, 273.9)
        self.assertEqual(snapshot.sales_forecast, 50_000_000.0)
        self.assertEqual(snapshot.earnings_date, "2026-02-06")

    def test_kabutan_source_missing_value_raises_fetch_error(self) -> None:
        stock_url = "https://kabutan.jp/stock/?code=7203"
        finance_url = "https://kabutan.jp/stock/finance?code=7203"
        stock_html = "<th scope='row'>終値</th><td>3,705</td>"
        finance_html = """
        <table>
          <tr>
            <th scope='row'>I 予 2026.03</th>
            <td>50,000,000</td><td>3,800,000</td><td>5,020,000</td><td>3,570,000</td><td>-</td><td>95</td><td>26/02/06</td>
          </tr>
        </table>
        """
        client = FakeHttpClient(
            {
                stock_url: FakeResponse(200, stock_html),
                finance_url: FakeResponse(200, finance_html),
            }
        )
        source = KabutanMarketDataSource(http_client=client)
        with self.assertRaises(MarketDataFetchError) as ctx:
            source.fetch_snapshot("7203:TSE")
        self.assertIn("eps_forecast", str(ctx.exception))

    def test_yahoo_source_parses_snapshot(self) -> None:
        quote_url = "https://finance.yahoo.co.jp/quote/7203.T"
        performance_url = "https://finance.yahoo.co.jp/quote/7203.T/performance"
        quote_html = """
        <script>
        window.__PRELOADED_STATE__ = {
          "mainStocksPriceBoard": {"priceBoard": {"price": "3,705"}},
          "mainStocksDetail": {"referenceIndex": {"eps": "273.92"}},
          "mainStocksPressReleaseSummary": {"disclosedTime": "2026-02-06T14:00:00+09:00"}
        };
        </script>
        """
        performance_html = """
        <script>
        self.__next_f.push([1,"{\"forecast\":{\"yearEndDate\":\"2026-03-31\",\"netSales\":49000000000000}}"])
        </script>
        """
        client = FakeHttpClient(
            {
                quote_url: FakeResponse(200, quote_html),
                performance_url: FakeResponse(200, performance_html),
            }
        )
        source = YahooFinanceMarketDataSource(http_client=client)
        snapshot = source.fetch_snapshot("7203:TSE")

        self.assertEqual(snapshot.source, "Yahoo!ファイナンス")
        self.assertEqual(snapshot.close_price, 3705.0)
        self.assertEqual(snapshot.eps_forecast, 273.92)
        self.assertEqual(snapshot.sales_forecast, 49_000_000_000_000.0)
        self.assertEqual(snapshot.earnings_date, "2026-02-06")

    def test_yahoo_source_uses_financials_when_quote_has_no_earnings_date(self) -> None:
        quote_url = "https://finance.yahoo.co.jp/quote/7203.T"
        performance_url = "https://finance.yahoo.co.jp/quote/7203.T/performance"
        financials_url = "https://finance.yahoo.co.jp/quote/7203.T/financials"
        quote_html = """
        <script>
        window.__PRELOADED_STATE__ = {
          "mainStocksPriceBoard": {"priceBoard": {"price": "3,705"}},
          "mainStocksDetail": {"referenceIndex": {"eps": "273.92"}}
        };
        </script>
        """
        performance_html = "{\"forecast\":{\"netSales\":49000000000000}}"
        financials_html = "<time dateTime=\"2026-02-06T14:00:00+09:00\">2026年2月6日</time>"

        client = FakeHttpClient(
            {
                quote_url: FakeResponse(200, quote_html),
                performance_url: FakeResponse(200, performance_html),
                financials_url: FakeResponse(200, financials_html),
            }
        )
        source = YahooFinanceMarketDataSource(http_client=client)
        snapshot = source.fetch_snapshot("7203:TSE")
        self.assertEqual(snapshot.earnings_date, "2026-02-06")

    def test_yahoo_source_missing_sales_raises_fetch_error(self) -> None:
        quote_url = "https://finance.yahoo.co.jp/quote/7203.T"
        performance_url = "https://finance.yahoo.co.jp/quote/7203.T/performance"
        quote_html = """
        {
          "mainStocksPriceBoard": {"priceBoard": {"price": "3,705"}},
          "mainStocksDetail": {"referenceIndex": {"eps": "273.92"}},
          "mainStocksPressReleaseSummary": {"disclosedTime": "2026-02-06T14:00:00+09:00"}
        }
        """
        performance_html = "{}"

        client = FakeHttpClient(
            {
                quote_url: FakeResponse(200, quote_html),
                performance_url: FakeResponse(200, performance_html),
            }
        )
        source = YahooFinanceMarketDataSource(http_client=client)
        with self.assertRaises(MarketDataFetchError) as ctx:
            source.fetch_snapshot("7203:TSE")
        self.assertIn("sales_forecast", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

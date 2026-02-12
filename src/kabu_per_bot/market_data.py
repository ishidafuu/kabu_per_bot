from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import html
import logging
import re
from typing import Protocol

import httpx

from kabu_per_bot.storage.firestore_schema import normalize_ticker


LOGGER = logging.getLogger(__name__)


class MarketDataError(RuntimeError):
    """Base error for market data fetching."""


class MarketDataFetchError(MarketDataError):
    def __init__(self, *, source: str, ticker: str, reason: str) -> None:
        self.source = source
        self.ticker = normalize_ticker(ticker)
        self.reason = reason.strip() or "unknown error"
        super().__init__(f"{source} failed for {self.ticker}: {self.reason}")


class MarketDataUnavailableError(MarketDataError):
    def __init__(self, *, ticker: str, reasons: list[str]) -> None:
        self.ticker = normalize_ticker(ticker)
        self.reasons = list(reasons)
        message = "; ".join(self.reasons) if self.reasons else "no sources configured"
        super().__init__(f"all market data sources failed for {self.ticker}: {message}")


@dataclass(frozen=True)
class MarketDataSnapshot:
    ticker: str
    close_price: float | None
    eps_forecast: float | None
    sales_forecast: float | None
    market_cap: float | None
    earnings_date: str | None
    source: str
    fetched_at: str

    @classmethod
    def create(
        cls,
        *,
        ticker: str,
        close_price: float | None,
        eps_forecast: float | None,
        sales_forecast: float | None,
        market_cap: float | None = None,
        earnings_date: str | None = None,
        source: str,
        fetched_at: str | None = None,
    ) -> "MarketDataSnapshot":
        return cls(
            ticker=normalize_ticker(ticker),
            close_price=close_price,
            eps_forecast=eps_forecast,
            sales_forecast=sales_forecast,
            market_cap=market_cap,
            earnings_date=earnings_date,
            source=source.strip(),
            fetched_at=fetched_at or datetime.now(timezone.utc).isoformat(),
        )

    def missing_fields(self) -> list[str]:
        fields: list[str] = []
        if self.close_price is None:
            fields.append("close_price")
        if self.eps_forecast is None:
            fields.append("eps_forecast")
        if self.sales_forecast is None:
            fields.append("sales_forecast")
        if not self.earnings_date:
            fields.append("earnings_date")
        return fields


class MarketDataSource(Protocol):
    @property
    def source_name(self) -> str:
        """Source name for logs."""

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        """Fetch market data snapshot."""


class FallbackMarketDataSource:
    def __init__(self, sources: list[MarketDataSource]) -> None:
        self._sources = list(sources)

    @property
    def source_name(self) -> str:
        return "fallback"

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        normalized_ticker = normalize_ticker(ticker)
        errors: list[str] = []
        if not self._sources:
            raise MarketDataUnavailableError(ticker=normalized_ticker, reasons=["source list is empty"])

        for source in self._sources:
            source_name = getattr(source, "source_name", source.__class__.__name__)
            try:
                return source.fetch_snapshot(normalized_ticker)
            except MarketDataFetchError as exc:
                LOGGER.warning("市場データ取得失敗: source=%s ticker=%s reason=%s", source_name, normalized_ticker, exc.reason)
                errors.append(str(exc))
            except Exception as exc:  # pragma: no cover - defensive guard
                LOGGER.exception("市場データ取得中の予期せぬ失敗: source=%s ticker=%s", source_name, normalized_ticker)
                errors.append(f"{source_name} failed for {normalized_ticker}: {exc}")
        raise MarketDataUnavailableError(ticker=normalized_ticker, reasons=errors)


class _HttpMarketDataSource:
    _DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (compatible; kabu-per-bot/1.0)",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    def __init__(
        self,
        source_name: str,
        *,
        http_client: httpx.Client | None = None,
        timeout_sec: float = 15.0,
    ) -> None:
        self._source_name = source_name
        self._timeout_sec = timeout_sec
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.Client(headers=self._DEFAULT_HEADERS, follow_redirects=True)

    @property
    def source_name(self) -> str:
        return self._source_name

    def _request_text(self, *, url: str, ticker: str) -> str:
        try:
            response = self._http_client.get(url, timeout=self._timeout_sec)
        except Exception as exc:
            raise MarketDataFetchError(source=self.source_name, ticker=ticker, reason=f"HTTP request error ({url}): {exc}") from exc

        status_code = int(getattr(response, "status_code", 0))
        if status_code >= 400:
            raise MarketDataFetchError(
                source=self.source_name,
                ticker=ticker,
                reason=f"HTTP status {status_code} ({url})",
            )

        body = str(getattr(response, "text", ""))
        if not body.strip():
            raise MarketDataFetchError(source=self.source_name, ticker=ticker, reason=f"empty response body ({url})")
        return body

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        if self._owns_client:
            try:
                self._http_client.close()
            except Exception:
                pass


class ShikihoMarketDataSource(_HttpMarketDataSource):
    def __init__(self, *, http_client: httpx.Client | None = None, timeout_sec: float = 15.0) -> None:
        super().__init__("四季報online", http_client=http_client, timeout_sec=timeout_sec)

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        normalized_ticker = normalize_ticker(ticker)
        code = _ticker_code(normalized_ticker)
        url = f"https://shikiho.toyokeizai.net/stocks/{code}"
        page = self._request_text(url=url, ticker=normalized_ticker)

        if "このブラウザではご利用いただけません" in page or "Cookieをオンにしてください" in page:
            raise MarketDataFetchError(
                source=self.source_name,
                ticker=normalized_ticker,
                reason="サイト側でブラウザ要件によりデータ取得不可（JavaScript/Cookie制限）",
            )

        close_price = _try_parse_number(page, _PRICE_PATTERNS, label="close_price")
        eps_forecast = _try_parse_number(page, _EPS_PATTERNS, label="eps_forecast")
        sales_forecast = _try_parse_number(page, _SALES_PATTERNS, label="sales_forecast")
        earnings_date = _try_parse_date(page, _EARNINGS_DATE_PATTERNS, label="earnings_date")

        errors = _required_field_errors(
            close_price=close_price,
            eps_forecast=eps_forecast,
            sales_forecast=sales_forecast,
            earnings_date=earnings_date,
        )
        if errors:
            raise MarketDataFetchError(source=self.source_name, ticker=normalized_ticker, reason="; ".join(errors))

        return MarketDataSnapshot.create(
            ticker=normalized_ticker,
            close_price=close_price,
            eps_forecast=eps_forecast,
            sales_forecast=sales_forecast,
            earnings_date=earnings_date,
            source=self.source_name,
        )


class KabutanMarketDataSource(_HttpMarketDataSource):
    def __init__(self, *, http_client: httpx.Client | None = None, timeout_sec: float = 15.0) -> None:
        super().__init__("株探", http_client=http_client, timeout_sec=timeout_sec)

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        normalized_ticker = normalize_ticker(ticker)
        code = _ticker_code(normalized_ticker)

        stock_url = f"https://kabutan.jp/stock/?code={code}"
        finance_url = f"https://kabutan.jp/stock/finance?code={code}"

        stock_page = self._request_text(url=stock_url, ticker=normalized_ticker)
        finance_page = self._request_text(url=finance_url, ticker=normalized_ticker)

        close_price = _try_parse_number(stock_page, [r"<th[^>]*>\s*終値\s*</th>\s*<td[^>]*>\s*([^<]+)"], label="close_price")

        forecast_row = _find_first(finance_page, [r"<tr[^>]*>\s*<th[^>]*>.*?予.*?</th>(.*?)</tr>"])
        sales_forecast: float | None = None
        eps_forecast: float | None = None
        earnings_date: str | None = None

        if forecast_row:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", forecast_row, flags=re.S)
            if len(cells) >= 5:
                try:
                    sales_forecast = _parse_number(_strip_tags(cells[0]))
                except ValueError:
                    sales_forecast = None
                try:
                    eps_forecast = _parse_number(_strip_tags(cells[4]))
                except ValueError:
                    eps_forecast = None
            if cells:
                try:
                    earnings_date = _parse_date_text(_strip_tags(cells[-1]))
                except ValueError:
                    earnings_date = None

        errors = _required_field_errors(
            close_price=close_price,
            eps_forecast=eps_forecast,
            sales_forecast=sales_forecast,
            earnings_date=earnings_date,
        )
        if errors:
            raise MarketDataFetchError(source=self.source_name, ticker=normalized_ticker, reason="; ".join(errors))

        return MarketDataSnapshot.create(
            ticker=normalized_ticker,
            close_price=close_price,
            eps_forecast=eps_forecast,
            sales_forecast=sales_forecast,
            earnings_date=earnings_date,
            source=self.source_name,
        )


class YahooFinanceMarketDataSource(_HttpMarketDataSource):
    def __init__(self, *, http_client: httpx.Client | None = None, timeout_sec: float = 15.0) -> None:
        super().__init__("Yahoo!ファイナンス", http_client=http_client, timeout_sec=timeout_sec)

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        normalized_ticker = normalize_ticker(ticker)
        code = _ticker_code(normalized_ticker)

        quote_url = f"https://finance.yahoo.co.jp/quote/{code}.T"
        performance_url = f"https://finance.yahoo.co.jp/quote/{code}.T/performance"
        financials_url = f"https://finance.yahoo.co.jp/quote/{code}.T/financials"

        quote_page = _decode_embedded_json(self._request_text(url=quote_url, ticker=normalized_ticker))
        performance_page = _decode_embedded_json(self._request_text(url=performance_url, ticker=normalized_ticker))

        close_price = _try_parse_number(
            quote_page,
            [
                r'"mainStocksPriceBoard"\s*:\s*\{.*?"price"\s*:\s*"([0-9,.-]+)"',
                r'"board"\s*:\s*\{.*?"price"\s*:\s*\{\s*"value"\s*:\s*"([0-9,.-]+)"',
            ],
            label="close_price",
        )

        eps_forecast = _try_parse_number(
            quote_page,
            [
                r'"referenceIndex"\s*:\s*\{.*?"eps"\s*:\s*"([0-9,.-]+)"',
                r'"eps"\s*:\s*"([0-9,.-]+)"\s*,\s*"epsDate"',
            ],
            label="eps_forecast",
        )

        sales_forecast = _try_parse_number(
            performance_page,
            [r'"forecast"\s*:\s*\{[^{}]*?"netSales"\s*:\s*([0-9.]+)'],
            label="sales_forecast",
        )

        earnings_date = _try_parse_date(
            quote_page,
            [
                r'"mainStocksPressReleaseSummary"\s*:\s*\{[^{}]*?"disclosedTime"\s*:\s*"([^"]+)"',
                r'"pressReleaseScheduleMessage"\s*:\s*"[^\"]*?(\d{4}年\d{1,2}月\d{1,2}日)[^\"]*"',
            ],
            label="earnings_date",
        )
        if earnings_date is None:
            financials_page = _decode_embedded_json(self._request_text(url=financials_url, ticker=normalized_ticker))
            earnings_date = _try_parse_date(
                financials_page,
                [
                    r'"dateTime"\s*:\s*"(\d{4}-\d{2}-\d{2})T',
                    r'"dateModified"\s*:\s*"(\d{4}-\d{2}-\d{2})',
                    r'dateTime="(\d{4}-\d{2}-\d{2})T',
                ],
                label="earnings_date",
            )

        errors = _required_field_errors(
            close_price=close_price,
            eps_forecast=eps_forecast,
            sales_forecast=sales_forecast,
            earnings_date=earnings_date,
        )
        if errors:
            raise MarketDataFetchError(source=self.source_name, ticker=normalized_ticker, reason="; ".join(errors))

        return MarketDataSnapshot.create(
            ticker=normalized_ticker,
            close_price=close_price,
            eps_forecast=eps_forecast,
            sales_forecast=sales_forecast,
            earnings_date=earnings_date,
            source=self.source_name,
        )


def create_default_market_data_source(
    *,
    shikiho_client: httpx.Client | None = None,
    kabutan_client: httpx.Client | None = None,
    yahoo_client: httpx.Client | None = None,
    timeout_sec: float = 15.0,
) -> FallbackMarketDataSource:
    return FallbackMarketDataSource(
        [
            ShikihoMarketDataSource(http_client=shikiho_client, timeout_sec=timeout_sec),
            KabutanMarketDataSource(http_client=kabutan_client, timeout_sec=timeout_sec),
            YahooFinanceMarketDataSource(http_client=yahoo_client, timeout_sec=timeout_sec),
        ]
    )


def _ticker_code(ticker: str) -> str:
    normalized_ticker = normalize_ticker(ticker)
    return normalized_ticker.split(":", 1)[0]


def _decode_embedded_json(page: str) -> str:
    return page.replace(r'\"', '"').replace(r'\u0026', '&')


def _strip_tags(value: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(stripped).strip()


def _find_first(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.S)
        if match:
            return match.group(1)
    return None


def _try_parse_number(text: str, patterns: list[str], *, label: str) -> float | None:
    token = _find_first(text, patterns)
    if token is None:
        return None
    try:
        return _parse_number(_strip_tags(token))
    except ValueError:
        LOGGER.warning("市場データ数値解析失敗: label=%s raw=%s", label, _strip_tags(token))
        return None


def _try_parse_date(text: str, patterns: list[str], *, label: str) -> str | None:
    token = _find_first(text, patterns)
    if token is None:
        return None
    try:
        return _parse_date_text(_strip_tags(token))
    except ValueError:
        LOGGER.warning("市場データ日付解析失敗: label=%s raw=%s", label, _strip_tags(token))
        return None


def _required_field_errors(
    *,
    close_price: float | None,
    eps_forecast: float | None,
    sales_forecast: float | None,
    earnings_date: str | None,
) -> list[str]:
    errors: list[str] = []
    if close_price is None:
        errors.append("close_price missing or unparsable")
    if eps_forecast is None:
        errors.append("eps_forecast missing or unparsable")
    if sales_forecast is None:
        errors.append("sales_forecast missing or unparsable")
    if earnings_date is None:
        errors.append("earnings_date missing or unparsable")
    return errors


def _parse_number(value: str) -> float:
    normalized = value.replace(",", "").replace(" ", "")
    normalized = normalized.replace("\u3000", "")
    normalized = normalized.replace("円", "").replace("株", "")

    if not normalized or normalized in {"-", "--", "---", "―", "－"}:
        raise ValueError(f"missing numeric value: {value}")

    if any(unit in normalized for unit in ("兆", "億", "万")):
        return _parse_japanese_large_number(normalized)

    token_match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not token_match:
        raise ValueError(f"no numeric token: {value}")
    return float(token_match.group(0))


def _parse_japanese_large_number(value: str) -> float:
    trillion = _extract_japanese_unit(value, "兆")
    hundred_million = _extract_japanese_unit(value, "億")
    ten_thousand = _extract_japanese_unit(value, "万")
    if trillion == 0 and hundred_million == 0 and ten_thousand == 0:
        raise ValueError(f"no japanese large-number unit: {value}")
    return trillion * 1_000_000_000_000 + hundred_million * 100_000_000 + ten_thousand * 10_000


def _extract_japanese_unit(value: str, unit: str) -> float:
    match = re.search(rf"(-?\d+(?:\.\d+)?)\s*{unit}", value)
    if not match:
        return 0.0
    return float(match.group(1))


def _parse_date_text(value: str) -> str:
    normalized = value.strip()

    for pattern in (
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})",
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
    ):
        match = re.search(pattern, normalized)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            return date(year, month, day).isoformat()

    short = re.search(r"(\d{2})/(\d{1,2})/(\d{1,2})", normalized)
    if short:
        year = 2000 + int(short.group(1))
        month = int(short.group(2))
        day = int(short.group(3))
        return date(year, month, day).isoformat()

    raise ValueError(f"unsupported date format: {value}")


_PRICE_PATTERNS = [
    r"終値[^\d-]{0,40}(-?\d[\d,]*(?:\.\d+)?)",
]

_EPS_PATTERNS = [
    r"(?:予想\s*EPS|EPS\s*予想|EPS)[^\d-]{0,40}(-?\d[\d,]*(?:\.\d+)?)",
    r"修正\s*1株益[^\d-]{0,40}(-?\d[\d,]*(?:\.\d+)?)",
]

_SALES_PATTERNS = [
    r"売上高(?:予想)?[^\d-]{0,40}(-?\d[\d,]*(?:\.\d+)?)",
    r"営業収益[^\d-]{0,40}(-?\d[\d,]*(?:\.\d+)?)",
]

_EARNINGS_DATE_PATTERNS = [
    r"(?:決算発表日|発表日|決算日)[^\d]{0,40}(\d{4}[/-]\d{1,2}[/-]\d{1,2}|\d{2}/\d{1,2}/\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日)",
]

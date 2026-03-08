from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from kabu_per_bot.jquants_v2 import JQuantsV2Client, normalize_jquants_code, normalize_jquants_date
from kabu_per_bot.storage.firestore_schema import normalize_trade_date
from kabu_per_bot.technical import PriceBarDaily, TechnicalSyncState
from kabu_per_bot.watchlist import WatchlistItem


DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS = 760
DEFAULT_TECHNICAL_OVERLAP_DAYS = 30
TECHNICAL_SYNC_STATE_SCHEMA_VERSION = 1
TECHNICAL_DATA_SOURCE = "J-Quants LITE"
TECHNICAL_DATA_SOURCE_PLAN = "light"
TECHNICAL_RAW_PAYLOAD_VERSION = "jquants_v2_equities_bars_daily"


class PriceBarDailyRepository(Protocol):
    def upsert(self, bar: PriceBarDaily) -> None:
        """Persist daily bar."""


class TechnicalSyncStateRepository(Protocol):
    def get(self, ticker: str) -> TechnicalSyncState | None:
        """Get sync state."""

    def upsert(self, state: TechnicalSyncState) -> None:
        """Persist sync state."""


@dataclass(frozen=True)
class TechnicalPriceSyncResult:
    ticker: str
    from_date: str
    to_date: str
    fetched_rows: int
    upserted_rows: int
    latest_fetched_trade_date: str | None
    full_refresh: bool


def resolve_technical_sync_from_date(
    *,
    latest_fetched_trade_date: str | None,
    to_date: str,
    initial_lookback_days: int = DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS,
    overlap_days: int = DEFAULT_TECHNICAL_OVERLAP_DAYS,
    full_refresh: bool = False,
) -> str:
    if initial_lookback_days <= 0:
        raise ValueError("initial_lookback_days must be > 0.")
    if overlap_days < 0:
        raise ValueError("overlap_days must be >= 0.")

    normalized_to = normalize_trade_date(to_date)
    to_day = date.fromisoformat(normalized_to)
    if full_refresh or latest_fetched_trade_date is None:
        return (to_day - timedelta(days=initial_lookback_days)).isoformat()

    latest_day = date.fromisoformat(normalize_trade_date(latest_fetched_trade_date))
    from_day = latest_day - timedelta(days=overlap_days)
    if from_day > to_day:
        return normalized_to
    return from_day.isoformat()


def sync_ticker_price_bars(
    *,
    item: WatchlistItem,
    from_date: str,
    to_date: str,
    jquants_client: JQuantsV2Client,
    price_bars_repo: PriceBarDailyRepository,
    sync_state_repo: TechnicalSyncStateRepository,
    fetched_at: str | None = None,
    full_refresh: bool = False,
) -> TechnicalPriceSyncResult:
    normalized_from = normalize_trade_date(from_date)
    normalized_to = normalize_trade_date(to_date)
    resolved_fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    previous_state = sync_state_repo.get(item.ticker)

    try:
        rows = jquants_client.get_eq_bars_daily(
            code_or_ticker=item.ticker,
            from_date=normalized_from,
            to_date=normalized_to,
        )
        bars = build_price_bars_from_jquants_rows(
            ticker=item.ticker,
            rows=rows,
            fetched_at=resolved_fetched_at,
        )

        upserted_rows = 0
        latest_fetched_trade_date = previous_state.latest_fetched_trade_date if previous_state is not None else None
        for bar in bars:
            price_bars_repo.upsert(bar)
            upserted_rows += 1
            latest_fetched_trade_date = bar.trade_date

        sync_state_repo.upsert(
            TechnicalSyncState(
                ticker=item.ticker,
                latest_fetched_trade_date=latest_fetched_trade_date,
                latest_calculated_trade_date=(
                    previous_state.latest_calculated_trade_date if previous_state is not None else None
                ),
                last_run_at=resolved_fetched_at,
                last_status="SUCCESS" if bars else "NO_DATA",
                last_fetch_from=normalized_from,
                last_fetch_to=normalized_to,
                last_error=None,
                last_full_refresh_at=(
                    resolved_fetched_at
                    if full_refresh
                    else (previous_state.last_full_refresh_at if previous_state is not None else None)
                ),
                schema_version=TECHNICAL_SYNC_STATE_SCHEMA_VERSION,
            )
        )
        return TechnicalPriceSyncResult(
            ticker=item.ticker,
            from_date=normalized_from,
            to_date=normalized_to,
            fetched_rows=len(rows),
            upserted_rows=upserted_rows,
            latest_fetched_trade_date=latest_fetched_trade_date,
            full_refresh=full_refresh,
        )
    except Exception as exc:
        sync_state_repo.upsert(
            TechnicalSyncState(
                ticker=item.ticker,
                latest_fetched_trade_date=previous_state.latest_fetched_trade_date if previous_state is not None else None,
                latest_calculated_trade_date=(
                    previous_state.latest_calculated_trade_date if previous_state is not None else None
                ),
                last_run_at=resolved_fetched_at,
                last_status="ERROR",
                last_fetch_from=normalized_from,
                last_fetch_to=normalized_to,
                last_error=str(exc),
                last_full_refresh_at=previous_state.last_full_refresh_at if previous_state is not None else None,
                schema_version=TECHNICAL_SYNC_STATE_SCHEMA_VERSION,
            )
        )
        raise


def build_price_bars_from_jquants_rows(
    *,
    ticker: str,
    rows: list[dict[str, Any]],
    fetched_at: str,
) -> list[PriceBarDaily]:
    bars: list[PriceBarDaily] = []
    for row in rows:
        trade_date = normalize_jquants_date(_required_value(row, keys=("Date", "date")))
        code = normalize_jquants_code(_required_value(row, keys=("Code", "code")))
        bars.append(
            PriceBarDaily(
                ticker=ticker,
                trade_date=trade_date,
                code=code,
                date=trade_date,
                open_price=_optional_float(row, keys=("Open", "O", "open")),
                high_price=_optional_float(row, keys=("High", "H", "high")),
                low_price=_optional_float(row, keys=("Low", "L", "low")),
                close_price=_optional_float(row, keys=("Close", "C", "close")),
                volume=_optional_int(row, keys=("Volume", "V", "volume")),
                turnover_value=_optional_float(
                    row,
                    keys=("TurnoverValue", "Turnover_Value", "turnover_value", "Value"),
                ),
                adj_open=_optional_float(
                    row,
                    keys=("AdjustmentOpen", "AdjustedOpen", "AdjOpen", "adjustment_open"),
                ),
                adj_high=_optional_float(
                    row,
                    keys=("AdjustmentHigh", "AdjustedHigh", "AdjHigh", "adjustment_high"),
                ),
                adj_low=_optional_float(
                    row,
                    keys=("AdjustmentLow", "AdjustedLow", "AdjLow", "adjustment_low"),
                ),
                adj_close=_optional_float(
                    row,
                    keys=("AdjustmentClose", "AdjustedClose", "AdjClose", "adjustment_close"),
                ),
                adj_volume=_optional_float(
                    row,
                    keys=("AdjustmentVolume", "AdjustedVolume", "AdjVolume", "adjustment_volume"),
                ),
                source=TECHNICAL_DATA_SOURCE,
                fetched_at=fetched_at,
                data_source_plan=TECHNICAL_DATA_SOURCE_PLAN,
                raw_payload_version=TECHNICAL_RAW_PAYLOAD_VERSION,
                updated_at=fetched_at,
            )
        )
    bars.sort(key=lambda row: row.trade_date)
    return bars


def _required_value(row: dict[str, Any], *, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] not in {None, ""}:
            return row[key]
    raise ValueError(f"required key not found: {keys}")


def _optional_float(row: dict[str, Any], *, keys: tuple[str, ...]) -> float | None:
    value = _optional_value(row, keys=keys)
    if value is None:
        return None
    return float(value)


def _optional_int(row: dict[str, Any], *, keys: tuple[str, ...]) -> int | None:
    value = _optional_value(row, keys=keys)
    if value is None:
        return None
    return int(value)


def _optional_value(row: dict[str, Any], *, keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        if key not in row:
            continue
        value = row[key]
        if value in {None, ""}:
            return None
        return value
    return None

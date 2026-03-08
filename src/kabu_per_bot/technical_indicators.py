from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from statistics import mean, median, stdev
from typing import Protocol

from kabu_per_bot.storage.firestore_schema import normalize_ticker
from kabu_per_bot.technical import PriceBarDaily, TechnicalIndicatorsDaily, TechnicalSyncState
from kabu_per_bot.technical_profile_runtime import (
    TechnicalProfileRuntimeSettings,
    resolve_technical_profile_runtime_settings,
)
from kabu_per_bot.technical_profiles import TechnicalProfile


TECHNICAL_INDICATOR_SCHEMA_VERSION = 1
TECHNICAL_READ_WINDOW_DAYS = 520
TECHNICAL_REWRITE_WINDOW_DAYS = 260


class PriceBarDailyReader(Protocol):
    def list_recent(self, ticker: str, *, limit: int) -> list[PriceBarDaily]:
        """Get recent price bars."""


class TechnicalIndicatorsDailyWriter(Protocol):
    def upsert(self, indicators: TechnicalIndicatorsDaily) -> None:
        """Persist technical indicators."""


class TechnicalSyncStateReaderWriter(Protocol):
    def get(self, ticker: str) -> TechnicalSyncState | None:
        """Get sync state."""

    def upsert(self, state: TechnicalSyncState) -> None:
        """Persist sync state."""


@dataclass(frozen=True)
class TechnicalIndicatorRefreshResult:
    ticker: str
    read_rows: int
    written_rows: int
    latest_calculated_trade_date: str | None


def calculate_technical_indicators_for_bars(
    *,
    ticker: str,
    bars: list[PriceBarDaily],
    profile: TechnicalProfile | None = None,
    schema_version: int = TECHNICAL_INDICATOR_SCHEMA_VERSION,
    calculated_at: str | None = None,
) -> list[TechnicalIndicatorsDaily]:
    if not bars:
        return []

    normalized_ticker = normalize_ticker(ticker)
    sorted_bars = sorted(bars, key=lambda row: row.trade_date)
    resolved_calculated_at = calculated_at or datetime.now(timezone.utc).isoformat()
    runtime = resolve_technical_profile_runtime_settings(profile)

    ma5_values: list[float | None] = []
    ma25_values: list[float | None] = []
    ma75_values: list[float | None] = []
    ma200_values: list[float | None] = []
    high20_values: list[float | None] = []
    high52w_values: list[float | None] = []
    ytd_high_values: list[float | None] = []
    trend_mid_up_values: list[bool] = []

    rows: list[TechnicalIndicatorsDaily] = []

    for index, bar in enumerate(sorted_bars):
        prev_bar = sorted_bars[index - 1] if index > 0 else None

        close = bar.close_price
        open_price = bar.open_price
        high = bar.high_price
        low = bar.low_price
        prev_close = prev_bar.close_price if prev_bar is not None else None
        change = _subtract(close, prev_close)
        change_pct = _pct_change(close, prev_close)
        intraday_range = _subtract(high, low)
        intraday_range_pct = _pct_of(intraday_range, close)

        ma_5 = _rolling_mean(sorted_bars, index, "adj_close", 5)
        ma_25 = _rolling_mean(sorted_bars, index, "adj_close", 25)
        ma_75 = _rolling_mean(sorted_bars, index, "adj_close", 75)
        ma_200 = _rolling_mean(sorted_bars, index, "adj_close", 200)
        ma5_values.append(ma_5)
        ma25_values.append(ma_25)
        ma75_values.append(ma_75)
        ma200_values.append(ma_200)

        dev_5 = _pct_change(bar.adj_close, ma_5)
        dev_25 = _pct_change(bar.adj_close, ma_25)
        dev_75 = _pct_change(bar.adj_close, ma_75)
        dev_200 = _pct_change(bar.adj_close, ma_200)
        close_vs_ma5 = dev_5
        close_vs_ma25 = dev_25
        close_vs_ma75 = dev_75
        close_vs_ma200 = dev_200

        slope_ma25 = _pct_change(ma_25, ma25_values[index - 5] if index >= 5 else None)
        slope_ma75 = _pct_change(ma_75, ma75_values[index - 10] if index >= 10 else None)
        slope_ma200 = _pct_change(ma_200, ma200_values[index - 20] if index >= 20 else None)

        ma_alignment = _ma_alignment_short_mid_long(ma_5=ma_5, ma_25=ma_25, ma_75=ma_75)
        perfect_order_flag = bool(
            ma_5 is not None
            and ma_25 is not None
            and ma_75 is not None
            and ma_200 is not None
            and slope_ma25 is not None
            and slope_ma75 is not None
            and slope_ma200 is not None
            and ma_5 > ma_25 > ma_75 > ma_200
            and slope_ma25 > 0
            and slope_ma75 > 0
            and slope_ma200 > 0
        )

        ytd_bars = _year_to_date_bars(sorted_bars, index)
        ytd_high = _max_attr(ytd_bars, "adj_high")
        ytd_low = _min_attr(ytd_bars, "adj_low")
        ytd_high_values.append(ytd_high)
        drawdown_from_ytd_high = _pct_change(bar.adj_close, ytd_high)
        rebound_from_ytd_low = _pct_change(bar.adj_close, ytd_low)

        high_20d = _rolling_max(sorted_bars, index, "adj_high", 20)
        low_20d = _rolling_min(sorted_bars, index, "adj_low", 20)
        high_52w = _rolling_max(sorted_bars, index, "adj_high", 252)
        low_52w = _rolling_min(sorted_bars, index, "adj_low", 252)
        high20_values.append(high_20d)
        high52w_values.append(high_52w)

        drawdown_from_52w_high = _pct_change(bar.adj_close, high_52w)
        new_high_20d = _is_new_high(sorted_bars, index, "adj_high", 20)
        new_high_52w = _is_new_high(sorted_bars, index, "adj_high", 252)
        new_low_20d = _is_new_low(sorted_bars, index, "adj_low", 20)
        new_low_52w = _is_new_low(sorted_bars, index, "adj_low", 252)
        days_from_20d_high = _days_from_window_high(sorted_bars, index, "adj_high", 20)
        days_from_ytd_high = _days_from_year_high(sorted_bars, index)
        days_from_52w_high = _days_from_window_high(sorted_bars, index, "adj_high", 252)

        volume = bar.volume
        turnover_value = bar.turnover_value
        avg_volume_20d = _rolling_mean(sorted_bars, index, "volume", 20)
        avg_turnover_20d = _rolling_mean(sorted_bars, index, "turnover_value", 20)
        median_volume_20d = _rolling_median(sorted_bars, index, "volume", 20)
        median_turnover_20d = _rolling_median(sorted_bars, index, "turnover_value", 20)
        median_turnover_60d = _rolling_median(sorted_bars, index, "turnover_value", 60)
        volume_ratio = _ratio(volume, avg_volume_20d)
        turnover_ratio = _ratio(turnover_value, avg_turnover_20d)
        turnover_stability_flag = bool(
            median_turnover_20d is not None
            and median_turnover_60d is not None
            and median_turnover_20d >= 100_000_000
            and median_turnover_60d >= 100_000_000
            and median_turnover_20d >= median_turnover_60d * 0.8
        )

        body_ratio = _body_ratio(bar)
        true_range = _true_range(bar=bar, prev_close=prev_close)
        close_position_in_range = _close_position_in_range(bar)
        upper_shadow_ratio = _upper_shadow_ratio(bar)
        lower_shadow_ratio = _lower_shadow_ratio(bar)
        gap_up_down_pct = _pct_change(open_price, prev_close)
        candle_type = _candle_type(
            bar=bar,
            body_ratio=body_ratio,
            upper_shadow_ratio=upper_shadow_ratio,
            lower_shadow_ratio=lower_shadow_ratio,
        )

        return_3d = _return_pct(sorted_bars, index, 3)
        return_5d = _return_pct(sorted_bars, index, 5)
        return_10d = _return_pct(sorted_bars, index, 10)
        return_20d = _return_pct(sorted_bars, index, 20)
        return_60d = _return_pct(sorted_bars, index, 60)

        atr_14 = _rolling_true_range_mean(sorted_bars, index, 14)
        atr_pct_14 = _pct_of(atr_14, bar.adj_close)
        volatility_20d = _volatility_20d(sorted_bars, index)

        above_ma5 = _gt(bar.adj_close, ma_5)
        above_ma25 = _gt(bar.adj_close, ma_25)
        above_ma75 = _gt(bar.adj_close, ma_75)
        above_ma200 = _gt(bar.adj_close, ma_200)
        high_52w_near = bool(high_52w is not None and bar.adj_close is not None and bar.adj_close >= high_52w * 0.97)
        ytd_high_near = bool(
            ytd_high is not None
            and bar.adj_close is not None
            and bar.adj_close >= ytd_high * runtime.ytd_high_near_ratio
        )
        trend_short_up = bool(above_ma25 and _gt(ma_5, ma_25) and _gt(slope_ma25, 0))
        trend_mid_up = bool(above_ma75 and _gt(ma_25, ma_75) and _gt(slope_ma75, 0))
        trend_mid_up_values.append(trend_mid_up)
        trend_long_up = bool(above_ma200 and _gt(ma_75, ma_200) and _gt(slope_ma200, 0))
        overheated_short = bool(dev_25 is not None and dev_25 >= runtime.overheated_short)
        overheated_mid = bool(dev_75 is not None and dev_75 >= runtime.overheated_mid)
        liquidity_ok = bool(avg_turnover_20d is not None and avg_turnover_20d >= runtime.liquidity_ok)
        volume_expanding = bool(volume_ratio is not None and volume_ratio >= runtime.volume_expanding)
        turnover_expanding = bool(turnover_ratio is not None and turnover_ratio >= runtime.turnover_expanding)
        breakdown_ma75 = bool(ma_75 is not None and bar.adj_close is not None and bar.adj_close < ma_75)
        rebound_from_ma25 = _rebound_from_ma(
            bars=sorted_bars,
            ma_values=ma25_values,
            runtime=runtime,
            index=index,
            lookback_days=5,
            current_close=bar.adj_close,
            current_ma=ma_25,
            change_pct=change_pct,
            close_position_in_range=close_position_in_range,
        )
        rebound_from_ma75 = _rebound_from_ma(
            bars=sorted_bars,
            ma_values=ma75_values,
            runtime=runtime,
            index=index,
            lookback_days=10,
            current_close=bar.adj_close,
            current_ma=ma_75,
            change_pct=change_pct,
            close_position_in_range=close_position_in_range,
        )

        prev_adj_close = prev_bar.adj_close if prev_bar is not None else None
        prev_ma5 = ma5_values[index - 1] if index > 0 else None
        prev_ma25 = ma25_values[index - 1] if index > 0 else None
        prev_ma75 = ma75_values[index - 1] if index > 0 else None
        prev_ma200 = ma200_values[index - 1] if index > 0 else None
        cross_up_ma5 = _cross_up(prev_adj_close, prev_ma5, bar.adj_close, ma_5)
        cross_down_ma5 = _cross_down(prev_adj_close, prev_ma5, bar.adj_close, ma_5)
        cross_up_ma25 = _cross_up(prev_adj_close, prev_ma25, bar.adj_close, ma_25)
        cross_down_ma25 = _cross_down(prev_adj_close, prev_ma25, bar.adj_close, ma_25)
        cross_up_ma75 = _cross_up(prev_adj_close, prev_ma75, bar.adj_close, ma_75)
        cross_down_ma75 = _cross_down(prev_adj_close, prev_ma75, bar.adj_close, ma_75)
        cross_up_ma200 = _cross_up(prev_adj_close, prev_ma200, bar.adj_close, ma_200)
        cross_down_ma200 = _cross_down(prev_adj_close, prev_ma200, bar.adj_close, ma_200)
        new_ytd_high = _is_new_ytd_high(sorted_bars, index)
        near_ytd_high_breakout = bool(
            ytd_high is not None
            and turnover_ratio is not None
            and bar.adj_close is not None
            and bar.adj_close >= ytd_high * runtime.near_ytd_high_breakout_ratio
            and bar.adj_close < ytd_high
            and turnover_ratio >= runtime.near_ytd_high_breakout_turnover_ratio
        )
        turnover_spike = bool(turnover_ratio is not None and turnover_ratio >= runtime.turnover_spike)
        volume_spike = bool(volume_ratio is not None and volume_ratio >= runtime.volume_spike)
        sharp_drop_high_volume = bool(
            change_pct is not None
            and volume_ratio is not None
            and close_position_in_range is not None
            and change_pct <= runtime.sharp_drop_change_pct
            and volume_ratio >= runtime.sharp_drop_volume_ratio
            and close_position_in_range <= runtime.sharp_drop_close_position_max
        )
        rebound_after_pullback = _rebound_after_pullback(
            bars=sorted_bars,
            high20_values=high20_values,
            index=index,
            current_adj_close=bar.adj_close,
            current_ma25=ma_25,
            change_pct=change_pct,
        )
        prev_trend_mid_up = trend_mid_up_values[index - 1] if index > 0 else False
        trend_change_to_up = bool(
            index > 0
            and not prev_trend_mid_up
            and trend_mid_up
            and (cross_up_ma75 or _gt(ma_25, ma_75))
        )
        trend_change_to_down = bool(
            index > 0
            and prev_trend_mid_up
            and not trend_mid_up
            and (cross_down_ma75 or _lt(ma_25, ma_75))
        )

        values = {
            "close": close,
            "open": open_price,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "intraday_range": intraday_range,
            "intraday_range_pct": intraday_range_pct,
            "ma_5": ma_5,
            "ma_25": ma_25,
            "ma_75": ma_75,
            "ma_200": ma_200,
            "dev_5": dev_5,
            "dev_25": dev_25,
            "dev_75": dev_75,
            "dev_200": dev_200,
            "close_vs_ma5": close_vs_ma5,
            "close_vs_ma25": close_vs_ma25,
            "close_vs_ma75": close_vs_ma75,
            "close_vs_ma200": close_vs_ma200,
            "slope_ma25": slope_ma25,
            "slope_ma75": slope_ma75,
            "slope_ma200": slope_ma200,
            "ma_alignment_short_mid_long": ma_alignment,
            "perfect_order_flag": perfect_order_flag,
            "ytd_high": ytd_high,
            "ytd_low": ytd_low,
            "drawdown_from_ytd_high": drawdown_from_ytd_high,
            "rebound_from_ytd_low": rebound_from_ytd_low,
            "high_20d": high_20d,
            "low_20d": low_20d,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "drawdown_from_52w_high": drawdown_from_52w_high,
            "new_high_20d": new_high_20d,
            "new_high_52w": new_high_52w,
            "new_low_20d": new_low_20d,
            "new_low_52w": new_low_52w,
            "days_from_20d_high": days_from_20d_high,
            "days_from_ytd_high": days_from_ytd_high,
            "days_from_52w_high": days_from_52w_high,
            "volume": volume,
            "turnover_value": turnover_value,
            "avg_volume_20d": avg_volume_20d,
            "avg_turnover_20d": avg_turnover_20d,
            "median_volume_20d": median_volume_20d,
            "median_turnover_20d": median_turnover_20d,
            "median_turnover_60d": median_turnover_60d,
            "volume_ratio": volume_ratio,
            "turnover_ratio": turnover_ratio,
            "body_ratio": body_ratio,
            "true_range": true_range,
            "close_position_in_range": close_position_in_range,
            "upper_shadow_ratio": upper_shadow_ratio,
            "lower_shadow_ratio": lower_shadow_ratio,
            "gap_up_down_pct": gap_up_down_pct,
            "candle_type": candle_type,
            "return_3d": return_3d,
            "return_5d": return_5d,
            "return_10d": return_10d,
            "return_20d": return_20d,
            "return_60d": return_60d,
            "atr_14": atr_14,
            "atr_pct_14": atr_pct_14,
            "volatility_20d": volatility_20d,
            "trend_short_up": trend_short_up,
            "trend_mid_up": trend_mid_up,
            "trend_long_up": trend_long_up,
            "above_ma5": above_ma5,
            "above_ma25": above_ma25,
            "above_ma75": above_ma75,
            "above_ma200": above_ma200,
            "ytd_high_near": ytd_high_near,
            "high_52w_near": high_52w_near,
            "overheated_short": overheated_short,
            "overheated_mid": overheated_mid,
            "liquidity_ok": liquidity_ok,
            "volume_expanding": volume_expanding,
            "turnover_expanding": turnover_expanding,
            "breakdown_ma75": breakdown_ma75,
            "rebound_from_ma25": rebound_from_ma25,
            "rebound_from_ma75": rebound_from_ma75,
            "cross_up_ma5": cross_up_ma5,
            "cross_down_ma5": cross_down_ma5,
            "cross_up_ma25": cross_up_ma25,
            "cross_down_ma25": cross_down_ma25,
            "cross_up_ma75": cross_up_ma75,
            "cross_down_ma75": cross_down_ma75,
            "cross_up_ma200": cross_up_ma200,
            "cross_down_ma200": cross_down_ma200,
            "new_ytd_high": new_ytd_high,
            "near_ytd_high_breakout": near_ytd_high_breakout,
            "turnover_spike": turnover_spike,
            "volume_spike": volume_spike,
            "sharp_drop_high_volume": sharp_drop_high_volume,
            "rebound_after_pullback": rebound_after_pullback,
            "trend_change_to_up": trend_change_to_up,
            "trend_change_to_down": trend_change_to_down,
            "turnover_stability_flag": turnover_stability_flag,
        }
        rows.append(
            TechnicalIndicatorsDaily(
                ticker=normalized_ticker,
                trade_date=bar.trade_date,
                schema_version=schema_version,
                calculated_at=resolved_calculated_at,
                values=values,
            )
        )

    return rows


def recalculate_recent_technical_indicators(
    *,
    ticker: str,
    price_bars_repo: PriceBarDailyReader,
    indicators_repo: TechnicalIndicatorsDailyWriter,
    sync_state_repo: TechnicalSyncStateReaderWriter,
    profile: TechnicalProfile | None = None,
    read_limit: int = TECHNICAL_READ_WINDOW_DAYS,
    write_limit: int = TECHNICAL_REWRITE_WINDOW_DAYS,
    calculated_at: str | None = None,
) -> TechnicalIndicatorRefreshResult:
    if read_limit <= 0:
        raise ValueError("read_limit must be > 0.")
    if write_limit <= 0:
        raise ValueError("write_limit must be > 0.")

    resolved_calculated_at = calculated_at or datetime.now(timezone.utc).isoformat()
    previous_state = sync_state_repo.get(ticker)
    recent_latest_first = price_bars_repo.list_recent(ticker, limit=read_limit)
    if not recent_latest_first:
        return TechnicalIndicatorRefreshResult(
            ticker=normalize_ticker(ticker),
            read_rows=0,
            written_rows=0,
            latest_calculated_trade_date=None,
        )

    bars = list(reversed(recent_latest_first))
    calculated = calculate_technical_indicators_for_bars(
        ticker=ticker,
        bars=bars,
        profile=profile,
        schema_version=TECHNICAL_INDICATOR_SCHEMA_VERSION,
        calculated_at=resolved_calculated_at,
    )
    to_write = calculated[-write_limit:]

    try:
        for row in to_write:
            indicators_repo.upsert(row)
        sync_state_repo.upsert(
            TechnicalSyncState(
                ticker=ticker,
                latest_fetched_trade_date=previous_state.latest_fetched_trade_date if previous_state is not None else None,
                latest_calculated_trade_date=to_write[-1].trade_date,
                last_run_at=resolved_calculated_at,
                last_status="CALCULATED",
                last_fetch_from=previous_state.last_fetch_from if previous_state is not None else None,
                last_fetch_to=previous_state.last_fetch_to if previous_state is not None else None,
                last_error=None,
                last_full_refresh_at=previous_state.last_full_refresh_at if previous_state is not None else None,
                schema_version=previous_state.schema_version if previous_state is not None else 1,
            )
        )
    except Exception as exc:
        sync_state_repo.upsert(
            TechnicalSyncState(
                ticker=ticker,
                latest_fetched_trade_date=previous_state.latest_fetched_trade_date if previous_state is not None else None,
                latest_calculated_trade_date=(
                    previous_state.latest_calculated_trade_date if previous_state is not None else None
                ),
                last_run_at=resolved_calculated_at,
                last_status="CALC_ERROR",
                last_fetch_from=previous_state.last_fetch_from if previous_state is not None else None,
                last_fetch_to=previous_state.last_fetch_to if previous_state is not None else None,
                last_error=str(exc),
                last_full_refresh_at=previous_state.last_full_refresh_at if previous_state is not None else None,
                schema_version=previous_state.schema_version if previous_state is not None else 1,
            )
        )
        raise

    return TechnicalIndicatorRefreshResult(
        ticker=normalize_ticker(ticker),
        read_rows=len(bars),
        written_rows=len(to_write),
        latest_calculated_trade_date=to_write[-1].trade_date,
    )


def _rolling_mean(bars: list[PriceBarDaily], index: int, attr: str, window: int) -> float | None:
    values = _window_attr_values(bars, index, attr, window)
    if values is None:
        return None
    return float(mean(values))


def _rolling_median(bars: list[PriceBarDaily], index: int, attr: str, window: int) -> float | None:
    values = _window_attr_values(bars, index, attr, window)
    if values is None:
        return None
    return float(median(values))


def _rolling_max(bars: list[PriceBarDaily], index: int, attr: str, window: int) -> float | None:
    values = _window_attr_values(bars, index, attr, window)
    if values is None:
        return None
    return float(max(values))


def _rolling_min(bars: list[PriceBarDaily], index: int, attr: str, window: int) -> float | None:
    values = _window_attr_values(bars, index, attr, window)
    if values is None:
        return None
    return float(min(values))


def _window_attr_values(bars: list[PriceBarDaily], index: int, attr: str, window: int) -> list[float] | None:
    start = index - window + 1
    if start < 0:
        return None
    values: list[float] = []
    for bar in bars[start : index + 1]:
        value = getattr(bar, attr)
        if value is None:
            return None
        values.append(float(value))
    return values


def _year_to_date_bars(bars: list[PriceBarDaily], index: int) -> list[PriceBarDaily]:
    current_year = bars[index].trade_date[:4]
    return [bar for bar in bars[: index + 1] if bar.trade_date.startswith(current_year)]


def _max_attr(bars: list[PriceBarDaily], attr: str) -> float | None:
    if not bars:
        return None
    values = []
    for bar in bars:
        value = getattr(bar, attr)
        if value is None:
            return None
        values.append(float(value))
    return float(max(values))


def _min_attr(bars: list[PriceBarDaily], attr: str) -> float | None:
    if not bars:
        return None
    values = []
    for bar in bars:
        value = getattr(bar, attr)
        if value is None:
            return None
        values.append(float(value))
    return float(min(values))


def _is_new_high(bars: list[PriceBarDaily], index: int, attr: str, lookback: int) -> bool:
    if index < lookback:
        return False
    current = getattr(bars[index], attr)
    if current is None:
        return False
    values = []
    for bar in bars[index - lookback : index]:
        value = getattr(bar, attr)
        if value is None:
            return False
        values.append(float(value))
    return float(current) > max(values)


def _is_new_low(bars: list[PriceBarDaily], index: int, attr: str, lookback: int) -> bool:
    if index < lookback:
        return False
    current = getattr(bars[index], attr)
    if current is None:
        return False
    values = []
    for bar in bars[index - lookback : index]:
        value = getattr(bar, attr)
        if value is None:
            return False
        values.append(float(value))
    return float(current) < min(values)


def _days_from_window_high(bars: list[PriceBarDaily], index: int, attr: str, window: int) -> int | None:
    values = _window_attr_values(bars, index, attr, window)
    if values is None:
        return None
    max_value = max(values)
    last_index = max(pos for pos, value in enumerate(values) if value == max_value)
    return len(values) - 1 - last_index


def _days_from_year_high(bars: list[PriceBarDaily], index: int) -> int | None:
    year_bars = _year_to_date_bars(bars, index)
    if not year_bars:
        return None
    highs = []
    for bar in year_bars:
        if bar.adj_high is None:
            return None
        highs.append(float(bar.adj_high))
    max_value = max(highs)
    last_index = max(pos for pos, value in enumerate(highs) if value == max_value)
    return len(highs) - 1 - last_index


def _body_ratio(bar: PriceBarDaily) -> float | None:
    if bar.open_price is None or bar.close_price is None or bar.high_price is None or bar.low_price is None:
        return None
    if bar.high_price == bar.low_price:
        return 0.0
    return abs(bar.close_price - bar.open_price) / (bar.high_price - bar.low_price)


def _true_range(*, bar: PriceBarDaily, prev_close: float | None) -> float | None:
    if bar.high_price is None or bar.low_price is None or prev_close is None:
        return None
    return max(
        bar.high_price - bar.low_price,
        abs(bar.high_price - prev_close),
        abs(bar.low_price - prev_close),
    )


def _close_position_in_range(bar: PriceBarDaily) -> float | None:
    if bar.close_price is None or bar.high_price is None or bar.low_price is None:
        return None
    if bar.high_price == bar.low_price:
        return 0.5
    return (bar.close_price - bar.low_price) / (bar.high_price - bar.low_price)


def _upper_shadow_ratio(bar: PriceBarDaily) -> float | None:
    if bar.open_price is None or bar.close_price is None or bar.high_price is None or bar.low_price is None:
        return None
    if bar.high_price == bar.low_price:
        return 0.0
    return (bar.high_price - max(bar.open_price, bar.close_price)) / (bar.high_price - bar.low_price)


def _lower_shadow_ratio(bar: PriceBarDaily) -> float | None:
    if bar.open_price is None or bar.close_price is None or bar.high_price is None or bar.low_price is None:
        return None
    if bar.high_price == bar.low_price:
        return 0.0
    return (min(bar.open_price, bar.close_price) - bar.low_price) / (bar.high_price - bar.low_price)


def _candle_type(
    *,
    bar: PriceBarDaily,
    body_ratio: float | None,
    upper_shadow_ratio: float | None,
    lower_shadow_ratio: float | None,
) -> str | None:
    if bar.open_price is None or bar.close_price is None or bar.high_price is None or bar.low_price is None:
        return None
    if bar.high_price == bar.low_price:
        return "flat_bar"
    if upper_shadow_ratio is not None and body_ratio is not None and upper_shadow_ratio >= 0.4 and body_ratio <= 0.35:
        return "upper_rejection"
    if lower_shadow_ratio is not None and body_ratio is not None and lower_shadow_ratio >= 0.4 and body_ratio <= 0.35:
        return "lower_rejection"
    if body_ratio is not None and body_ratio <= 0.1:
        return "doji"
    if bar.close_price > bar.open_price:
        return "bull"
    if bar.close_price < bar.open_price:
        return "bear"
    return "doji"


def _return_pct(bars: list[PriceBarDaily], index: int, offset: int) -> float | None:
    if index < offset:
        return None
    return _pct_change(bars[index].adj_close, bars[index - offset].adj_close)


def _rolling_true_range_mean(bars: list[PriceBarDaily], index: int, window: int) -> float | None:
    if index < window - 1:
        return None
    values: list[float] = []
    for current_index in range(index - window + 1, index + 1):
        prev_close = bars[current_index - 1].close_price if current_index > 0 else None
        value = _true_range(bar=bars[current_index], prev_close=prev_close)
        if value is None:
            return None
        values.append(value)
    return float(mean(values))


def _volatility_20d(bars: list[PriceBarDaily], index: int) -> float | None:
    if index < 20:
        return None
    returns: list[float] = []
    for current_index in range(index - 19, index + 1):
        current_close = bars[current_index].adj_close
        prev_close = bars[current_index - 1].adj_close if current_index > 0 else None
        if current_close is None or prev_close is None or current_close <= 0 or prev_close <= 0:
            return None
        returns.append(math.log(current_close / prev_close))
    return float(stdev(returns) * math.sqrt(252) * 100)


def _ma_alignment_short_mid_long(*, ma_5: float | None, ma_25: float | None, ma_75: float | None) -> str | None:
    if ma_5 is None or ma_25 is None or ma_75 is None:
        return None
    pairs = [("ma5", ma_5), ("ma25", ma_25), ("ma75", ma_75)]
    pairs.sort(key=lambda row: row[1], reverse=True)
    return ">".join(name for name, _value in pairs)


def _rebound_from_ma(
    *,
    bars: list[PriceBarDaily],
    ma_values: list[float | None],
    runtime: TechnicalProfileRuntimeSettings,
    index: int,
    lookback_days: int,
    current_close: float | None,
    current_ma: float | None,
    change_pct: float | None,
    close_position_in_range: float | None,
) -> bool:
    if (
        current_close is None
        or current_ma is None
        or change_pct is None
        or close_position_in_range is None
        or current_close <= current_ma
        or change_pct <= 0
        or close_position_in_range < runtime.rebound_close_position_min
    ):
        return False
    start = max(0, index - lookback_days + 1)
    for current_index in range(start, index + 1):
        ma_value = ma_values[current_index]
        adj_low = bars[current_index].adj_low
        if ma_value is None or adj_low is None or ma_value == 0:
            continue
        if abs(adj_low / ma_value - 1) <= runtime.rebound_touch_band_pct / 100:
            return True
    return False


def _is_new_ytd_high(bars: list[PriceBarDaily], index: int) -> bool:
    year_bars = _year_to_date_bars(bars, index)
    if len(year_bars) <= 1:
        return False
    current_high = year_bars[-1].adj_high
    if current_high is None:
        return False
    previous_highs: list[float] = []
    for bar in year_bars[:-1]:
        if bar.adj_high is None:
            return False
        previous_highs.append(float(bar.adj_high))
    return float(current_high) > max(previous_highs)


def _rebound_after_pullback(
    *,
    bars: list[PriceBarDaily],
    high20_values: list[float | None],
    index: int,
    current_adj_close: float | None,
    current_ma25: float | None,
    change_pct: float | None,
) -> bool:
    if current_adj_close is None or current_ma25 is None or change_pct is None:
        return False
    if current_adj_close <= current_ma25 or change_pct < 2:
        return False
    start = max(0, index - 9)
    for current_index in range(start, index + 1):
        high20 = high20_values[current_index]
        adj_close = bars[current_index].adj_close
        if high20 is None or adj_close is None:
            continue
        if adj_close <= high20 * 0.92:
            return True
    return False


def _cross_up(
    prev_price: float | None,
    prev_ref: float | None,
    current_price: float | None,
    current_ref: float | None,
) -> bool:
    return bool(
        prev_price is not None
        and prev_ref is not None
        and current_price is not None
        and current_ref is not None
        and prev_price <= prev_ref
        and current_price > current_ref
    )


def _cross_down(
    prev_price: float | None,
    prev_ref: float | None,
    current_price: float | None,
    current_ref: float | None,
) -> bool:
    return bool(
        prev_price is not None
        and prev_ref is not None
        and current_price is not None
        and current_ref is not None
        and prev_price >= prev_ref
        and current_price < current_ref
    )


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current / previous - 1) * 100


def _pct_of(value: float | None, base: float | None) -> float | None:
    if value is None or base is None or base == 0:
        return None
    return (value / base) * 100


def _ratio(value: float | int | None, average: float | None) -> float | None:
    if value is None or average is None or average == 0:
        return None
    return float(value) / average


def _gt(left: float | None, right: float | None) -> bool:
    return bool(left is not None and right is not None and left > right)


def _lt(left: float | None, right: float | None) -> bool:
    return bool(left is not None and right is not None and left < right)

from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.market_data import MarketDataSnapshot
from kabu_per_bot.technical import TechnicalIndicatorsDaily
from kabu_per_bot.technical_profile_auto_assign import auto_assign_technical_profiles
from kabu_per_bot.technical_profiles import TechnicalProfile, TechnicalProfileType
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


@dataclass
class InMemoryWatchlistRepo:
    rows: dict[str, WatchlistItem] = field(default_factory=dict)

    def update(self, item: WatchlistItem) -> None:
        self.rows[item.ticker] = item


@dataclass
class InMemoryTechnicalIndicatorsRepo:
    rows: dict[str, list[TechnicalIndicatorsDaily]] = field(default_factory=dict)

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalIndicatorsDaily]:
        return self.rows.get(ticker, [])[:limit]


@dataclass
class InMemoryTechnicalProfilesRepo:
    rows: list[TechnicalProfile]

    def list_all(self, *, include_inactive: bool = True) -> list[TechnicalProfile]:
        if include_inactive:
            return list(self.rows)
        return [row for row in self.rows if row.is_active]


class StaticMarketDataSource:
    source_name = "static"

    def __init__(self, values: dict[str, float | None]) -> None:
        self._values = values

    def fetch_snapshot(self, ticker: str) -> MarketDataSnapshot:
        return MarketDataSnapshot.create(
            ticker=ticker,
            close_price=100,
            eps_forecast=10,
            sales_forecast=1000,
            market_cap=self._values.get(ticker),
            source="static",
            fetched_at="2026-03-08T00:00:00+00:00",
        )


def _item(ticker: str, *, manual_override: bool = False) -> WatchlistItem:
    return WatchlistItem(
        ticker=ticker,
        name=ticker,
        metric_type=MetricType.PER,
        notify_channel=NotifyChannel.DISCORD,
        notify_timing=NotifyTiming.IMMEDIATE,
        technical_profile_manual_override=manual_override,
    )


def _indicators(ticker: str, **values) -> TechnicalIndicatorsDaily:
    return TechnicalIndicatorsDaily(
        ticker=ticker,
        trade_date="2026-03-08",
        schema_version=1,
        calculated_at="2026-03-08T00:00:00+00:00",
        values=values,
    )


class TechnicalProfileAutoAssignTest(unittest.TestCase):
    def test_auto_assign_picks_first_matching_profile_and_skips_manual_override(self) -> None:
        watchlist_repo = InMemoryWatchlistRepo(
            rows={
                "3901:TSE": _item("3901:TSE"),
                "3902:TSE": _item("3902:TSE", manual_override=True),
            }
        )
        indicators_repo = InMemoryTechnicalIndicatorsRepo(
            rows={
                "3901:TSE": [_indicators("3901:TSE", avg_turnover_20d=50_000_000, median_turnover_20d=40_000_000)],
                "3902:TSE": [_indicators("3902:TSE", avg_turnover_20d=50_000_000, median_turnover_20d=40_000_000)],
            }
        )
        profiles_repo = InMemoryTechnicalProfilesRepo(
            rows=[
                TechnicalProfile(
                    profile_id="system_low_liquidity",
                    profile_type=TechnicalProfileType.SYSTEM,
                    profile_key="low_liquidity",
                    name="低流動性",
                    description="test",
                    priority_order=1,
                    auto_assign={"any": [{"avg_turnover_20d_lt": 100_000_000}]},
                ),
                TechnicalProfile(
                    profile_id="system_small_growth",
                    profile_type=TechnicalProfileType.SYSTEM,
                    profile_key="small_growth",
                    name="小型成長",
                    description="test",
                    priority_order=4,
                    auto_assign={"all": [{"market_cap_lt": 500_000_000_000}]},
                ),
            ]
        )

        result = auto_assign_technical_profiles(
            watchlist_items=list(watchlist_repo.rows.values()),
            watchlist_repo=watchlist_repo,
            technical_indicators_repo=indicators_repo,
            technical_profiles_repo=profiles_repo,
            market_data_source=StaticMarketDataSource({"3901:TSE": 200_000_000_000, "3902:TSE": 200_000_000_000}),
        )

        self.assertEqual(result.updated_tickers, 1)
        self.assertEqual(result.skipped_manual_override, 1)
        self.assertEqual(watchlist_repo.rows["3901:TSE"].technical_profile_id, "system_low_liquidity")
        self.assertIsNone(watchlist_repo.rows["3902:TSE"].technical_profile_id)

    def test_manual_only_profile_uses_fallback_when_enabled(self) -> None:
        watchlist_repo = InMemoryWatchlistRepo(rows={"3901:TSE": _item("3901:TSE")})
        indicators_repo = InMemoryTechnicalIndicatorsRepo(
            rows={"3901:TSE": [_indicators("3901:TSE", avg_turnover_20d=500_000_000, volatility_20d=20.0)]}
        )
        profiles_repo = InMemoryTechnicalProfilesRepo(
            rows=[
                TechnicalProfile(
                    profile_id="system_value_dividend",
                    profile_type=TechnicalProfileType.SYSTEM,
                    profile_key="value_dividend",
                    name="高配当",
                    description="test",
                    priority_order=3,
                    auto_assign={
                        "manual_only": True,
                        "fallback_rule": {
                            "all": [
                                {"market_cap_gte": 100_000_000_000},
                                {"avg_turnover_20d_gte": 300_000_000},
                                {"volatility_20d_lte": 25.0},
                            ]
                        },
                    },
                )
            ]
        )

        result = auto_assign_technical_profiles(
            watchlist_items=list(watchlist_repo.rows.values()),
            watchlist_repo=watchlist_repo,
            technical_indicators_repo=indicators_repo,
            technical_profiles_repo=profiles_repo,
            market_data_source=StaticMarketDataSource({"3901:TSE": 150_000_000_000}),
            allow_manual_fallback=True,
        )

        self.assertEqual(result.updated_tickers, 1)
        self.assertEqual(watchlist_repo.rows["3901:TSE"].technical_profile_id, "system_value_dividend")


if __name__ == "__main__":
    unittest.main()

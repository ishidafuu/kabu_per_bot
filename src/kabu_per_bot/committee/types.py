from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from statistics import mean
from typing import Any

from kabu_per_bot.market_data import MarketDataSnapshot
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.watchlist import MetricType


class LensDirection(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class LensKey(str, Enum):
    BUSINESS = "business"
    FINANCIAL = "financial"
    VALUATION = "valuation"
    TECHNICAL = "technical"
    EVENT = "event"
    RISK = "risk"


@dataclass(frozen=True)
class CommitteeContext:
    ticker: str
    company_name: str
    trade_date: str
    metric_type: MetricType
    latest_metric: DailyMetric | None
    recent_metrics: tuple[DailyMetric, ...]
    latest_medians: MetricMedians | None
    market_snapshot: MarketDataSnapshot | None
    baseline_summary: dict[str, Any] | None = None
    baseline_reliability_score: int | None = None
    baseline_updated_at: str | None = None

    @property
    def day_change_pct(self) -> float | None:
        history = self._close_history()
        if len(history) < 2:
            return None
        return _change_pct(history[0], history[1])

    @property
    def week_change_pct(self) -> float | None:
        history = self._close_history()
        if len(history) < 6:
            return None
        return _change_pct(history[0], history[5])

    def moving_average(self, days: int) -> float | None:
        if days <= 0:
            raise ValueError("days must be > 0")
        history = self._close_history()
        if len(history) < days:
            return None
        return float(mean(history[:days]))

    @property
    def earnings_days(self) -> int | None:
        if self.market_snapshot is None or not self.market_snapshot.earnings_date:
            return None
        try:
            current = date.fromisoformat(self.trade_date)
            earnings = date.fromisoformat(self.market_snapshot.earnings_date)
        except ValueError:
            return None
        return (earnings - current).days

    def metric_value(self) -> float | None:
        if self.latest_metric is None:
            return None
        if self.metric_type is MetricType.PER:
            return self.latest_metric.per_value
        return self.latest_metric.psr_value

    def _close_history(self) -> list[float]:
        values: list[float] = []
        for row in self.recent_metrics:
            if row.close_price is None or row.close_price <= 0:
                continue
            values.append(row.close_price)
        return values


@dataclass(frozen=True)
class LensEvaluation:
    key: LensKey
    title: str
    direction: LensDirection
    confidence: int
    strength: int
    lines: tuple[str, ...]
    missing_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", clamp_score(self.confidence))
        object.__setattr__(self, "strength", clamp_score(self.strength))
        object.__setattr__(self, "lines", normalize_lines(self.lines))


@dataclass(frozen=True)
class CommitteeEvaluation:
    ticker: str
    company_name: str
    trade_date: str
    confidence: int
    strength: int
    lenses: tuple[LensEvaluation, ...]
    missing_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", clamp_score(self.confidence))
        object.__setattr__(self, "strength", clamp_score(self.strength))


def clamp_score(value: int) -> int:
    if value < 1:
        return 1
    if value > 5:
        return 5
    return int(value)


def normalize_lines(lines: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in lines:
        text = str(raw).strip()
        if not text:
            continue
        normalized.append(text)
    if not normalized:
        normalized.append("評価材料が不足しています。")
    # 各観点コメントは最大3行
    return tuple(normalized[:3])


def _change_pct(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100.0

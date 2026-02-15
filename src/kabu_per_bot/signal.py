from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from kabu_per_bot.metrics import MetricMedians
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date
from kabu_per_bot.watchlist import MetricType


@dataclass(frozen=True)
class SignalEvaluation:
    ticker: str
    trade_date: str
    metric_type: MetricType
    metric_value: float | None
    under_1w: bool
    under_3m: bool
    under_1y: bool
    combo: str | None
    is_strong: bool
    category: str | None

    @property
    def has_signal(self) -> bool:
        return self.category is not None

    @property
    def condition_key(self) -> str | None:
        if not self.combo:
            return None
        return f"{self.metric_type.value}:{self.combo}"


@dataclass(frozen=True)
class SignalState:
    ticker: str
    trade_date: str
    metric_type: MetricType
    metric_value: float | None
    under_1w: bool
    under_3m: bool
    under_1y: bool
    combo: str | None
    is_strong: bool
    category: str | None
    streak_days: int
    updated_at: str

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "SignalState":
        return cls(
            ticker=normalize_ticker(str(data["ticker"])),
            trade_date=normalize_trade_date(str(data["trade_date"])),
            metric_type=MetricType(str(data["metric_type"]).strip().upper()),
            metric_value=_as_float(data.get("metric_value")),
            under_1w=bool(data.get("under_1w", False)),
            under_3m=bool(data.get("under_3m", False)),
            under_1y=bool(data.get("under_1y", False)),
            combo=str(data["combo"]) if data.get("combo") else None,
            is_strong=bool(data.get("is_strong", False)),
            category=str(data["category"]) if data.get("category") else None,
            streak_days=int(data.get("streak_days", 0)),
            updated_at=str(data.get("updated_at", "")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "metric_type": self.metric_type.value,
            "metric_value": self.metric_value,
            "under_1w": self.under_1w,
            "under_3m": self.under_3m,
            "under_1y": self.under_1y,
            "combo": self.combo,
            "is_strong": self.is_strong,
            "category": self.category,
            "streak_days": self.streak_days,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class NotificationLogEntry:
    entry_id: str
    ticker: str
    category: str
    condition_key: str
    sent_at: str
    channel: str
    payload_hash: str
    is_strong: bool

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "NotificationLogEntry":
        return cls(
            entry_id=str(data["id"]),
            ticker=normalize_ticker(str(data["ticker"])),
            category=str(data["category"]),
            condition_key=str(data["condition_key"]),
            sent_at=str(data["sent_at"]),
            channel=str(data["channel"]),
            payload_hash=str(data.get("payload_hash", "")),
            is_strong=bool(data.get("is_strong", False)),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "id": self.entry_id,
            "ticker": self.ticker,
            "category": self.category,
            "condition_key": self.condition_key,
            "sent_at": self.sent_at,
            "channel": self.channel,
            "payload_hash": self.payload_hash,
            "is_strong": self.is_strong,
        }


@dataclass(frozen=True)
class CooldownDecision:
    should_send: bool
    reason: str


def evaluate_signal(
    *,
    ticker: str,
    trade_date: str,
    metric_type: MetricType,
    metric_value: float | None,
    medians: MetricMedians,
) -> SignalEvaluation:
    normalized_ticker = normalize_ticker(ticker)
    normalized_trade_date = normalize_trade_date(trade_date)
    if metric_value is None:
        return SignalEvaluation(
            ticker=normalized_ticker,
            trade_date=normalized_trade_date,
            metric_type=metric_type,
            metric_value=None,
            under_1w=False,
            under_3m=False,
            under_1y=False,
            combo=None,
            is_strong=False,
            category=None,
        )

    under_1w = medians.median_1w is not None and metric_value < medians.median_1w
    under_3m = medians.median_3m is not None and metric_value < medians.median_3m
    under_1y = medians.median_1y is not None and metric_value < medians.median_1y

    is_strong = under_1y and under_3m and under_1w
    combo: str | None = None
    category: str | None = None

    if is_strong:
        combo = "1Y+3M+1W"
        category = "超PER割安" if metric_type is MetricType.PER else "超PSR割安"
    elif under_1y and under_3m:
        combo = "1Y+3M"
        category = "PER割安" if metric_type is MetricType.PER else "PSR割安"
    elif under_3m and under_1w:
        combo = "3M+1W"
        category = "PER割安" if metric_type is MetricType.PER else "PSR割安"
    elif under_1y and under_1w:
        combo = "1Y+1W"
        category = "PER割安" if metric_type is MetricType.PER else "PSR割安"

    return SignalEvaluation(
        ticker=normalized_ticker,
        trade_date=normalized_trade_date,
        metric_type=metric_type,
        metric_value=metric_value,
        under_1w=under_1w,
        under_3m=under_3m,
        under_1y=under_1y,
        combo=combo,
        is_strong=is_strong,
        category=category,
    )


def build_signal_state(
    *,
    evaluation: SignalEvaluation,
    previous_state: SignalState | None,
    updated_at: str | None = None,
) -> SignalState:
    streak_days = 0
    if evaluation.has_signal:
        streak_days = 1
        if (
            previous_state is not None
            and _is_same_signal(previous_state, evaluation)
            and _is_previous_business_day(previous_trade_date=previous_state.trade_date, current_trade_date=evaluation.trade_date)
        ):
            streak_days = previous_state.streak_days + 1

    return SignalState(
        ticker=evaluation.ticker,
        trade_date=evaluation.trade_date,
        metric_type=evaluation.metric_type,
        metric_value=evaluation.metric_value,
        under_1w=evaluation.under_1w,
        under_3m=evaluation.under_3m,
        under_1y=evaluation.under_1y,
        combo=evaluation.combo,
        is_strong=evaluation.is_strong,
        category=evaluation.category,
        streak_days=streak_days,
        updated_at=updated_at or datetime.now(timezone.utc).isoformat(),
    )


def evaluate_cooldown(
    *,
    now_iso: str,
    cooldown_hours: int,
    candidate_ticker: str,
    candidate_category: str,
    candidate_condition_key: str,
    candidate_is_strong: bool,
    recent_entries: list[NotificationLogEntry],
) -> CooldownDecision:
    if cooldown_hours <= 0:
        raise ValueError("cooldown_hours must be > 0")

    now = _parse_iso_datetime(now_iso)
    threshold = now - timedelta(hours=cooldown_hours)
    normalized_ticker = normalize_ticker(candidate_ticker)

    for entry in recent_entries:
        if entry.ticker != normalized_ticker:
            continue
        if entry.category != candidate_category:
            continue
        if entry.condition_key != candidate_condition_key:
            continue
        if _is_recent(entry.sent_at, threshold):
            return CooldownDecision(should_send=False, reason="2時間クールダウン中")

    if candidate_is_strong:
        metric_prefix = candidate_condition_key.split(":", 1)[0]
        for entry in recent_entries:
            if entry.ticker != normalized_ticker:
                continue
            if entry.is_strong:
                continue
            if _metric_prefix(entry.condition_key) != metric_prefix:
                continue
            if _is_recent(entry.sent_at, threshold):
                return CooldownDecision(should_send=True, reason="通常→強遷移のため即時通知")

    return CooldownDecision(should_send=True, reason="送信可")


def _is_same_signal(previous: SignalState, current: SignalEvaluation) -> bool:
    if previous.category != current.category:
        return False
    if previous.combo != current.combo:
        return False
    if previous.is_strong != current.is_strong:
        return False
    return True


def _is_previous_business_day(*, previous_trade_date: str, current_trade_date: str) -> bool:
    previous = date.fromisoformat(previous_trade_date)
    current = date.fromisoformat(current_trade_date)
    expected = current - timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= timedelta(days=1)
    return previous == expected


def _is_recent(sent_at: str, threshold: datetime) -> bool:
    sent = _parse_iso_datetime(sent_at)
    return sent >= threshold


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _metric_prefix(condition_key: str) -> str:
    return condition_key.split(":", 1)[0]


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed

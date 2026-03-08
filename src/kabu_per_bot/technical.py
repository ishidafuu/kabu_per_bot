from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import uuid
from typing import Any, Protocol

from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date


TECHNICAL_INDICATOR_FLOAT_FIELDS = (
    "body_ratio",
    "true_range",
    "close_position_in_range",
    "upper_shadow_ratio",
    "lower_shadow_ratio",
    "gap_up_down_pct",
    "drawdown_from_52w_high",
    "median_turnover_20d",
    "median_turnover_60d",
    "volatility_20d",
    "atr_14",
    "atr_pct_14",
    "close_vs_ma5",
    "close_vs_ma25",
    "close_vs_ma75",
    "close_vs_ma200",
    "slope_ma25",
    "slope_ma75",
    "slope_ma200",
)
TECHNICAL_INDICATOR_INT_FIELDS = (
    "days_from_20d_high",
    "days_from_ytd_high",
    "days_from_52w_high",
)
TECHNICAL_INDICATOR_BOOL_FIELDS = (
    "above_ma5",
    "cross_up_ma5",
    "cross_down_ma5",
    "above_ma200",
    "cross_up_ma200",
    "cross_down_ma200",
    "high_52w_near",
    "turnover_stability_flag",
)
TECHNICAL_INDICATOR_STRING_FIELDS = ("candle_type",)
TECHNICAL_INDICATOR_FIELD_KEYS = (
    *TECHNICAL_INDICATOR_FLOAT_FIELDS,
    *TECHNICAL_INDICATOR_INT_FIELDS,
    *TECHNICAL_INDICATOR_BOOL_FIELDS,
    *TECHNICAL_INDICATOR_STRING_FIELDS,
)
TECHNICAL_INDICATOR_FIELD_KEY_SET = frozenset(TECHNICAL_INDICATOR_FIELD_KEYS)
TECHNICAL_INDICATOR_FLOAT_FIELD_SET = frozenset(TECHNICAL_INDICATOR_FLOAT_FIELDS)
TECHNICAL_INDICATOR_INT_FIELD_SET = frozenset(TECHNICAL_INDICATOR_INT_FIELDS)
TECHNICAL_INDICATOR_BOOL_FIELD_SET = frozenset(TECHNICAL_INDICATOR_BOOL_FIELDS)
TECHNICAL_INDICATOR_STRING_FIELD_SET = frozenset(TECHNICAL_INDICATOR_STRING_FIELDS)


def is_valid_technical_indicator_field_key(field_key: str) -> bool:
    return field_key.strip() in TECHNICAL_INDICATOR_FIELD_KEY_SET


class TechnicalAlertOperator(str, Enum):
    IS_TRUE = "IS_TRUE"
    IS_FALSE = "IS_FALSE"
    GTE = "GTE"
    LTE = "LTE"
    BETWEEN = "BETWEEN"
    OUTSIDE = "OUTSIDE"


@dataclass(frozen=True)
class PriceBarDaily:
    ticker: str
    trade_date: str
    code: str
    date: str
    open_price: float | None
    high_price: float | None
    low_price: float | None
    close_price: float | None
    volume: int | None
    turnover_value: float | None
    adj_open: float | None
    adj_high: float | None
    adj_low: float | None
    adj_close: float | None
    adj_volume: float | None
    source: str
    fetched_at: str
    data_source_plan: str | None = None
    raw_payload_version: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", normalize_ticker(self.ticker))
        object.__setattr__(self, "trade_date", normalize_trade_date(self.trade_date))
        code = str(self.code).strip()
        if len(code) != 4 or not code.isdigit():
            raise ValueError(f"invalid code: {self.code}")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "date", normalize_trade_date(self.date))

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "PriceBarDaily":
        return cls(
            ticker=str(data["ticker"]),
            trade_date=str(data["trade_date"]),
            code=str(data["code"]),
            date=str(data["date"]),
            open_price=_as_float(data.get("open")),
            high_price=_as_float(data.get("high")),
            low_price=_as_float(data.get("low")),
            close_price=_as_float(data.get("close")),
            volume=_as_int(data.get("volume")),
            turnover_value=_as_float(data.get("turnover_value")),
            adj_open=_as_float(data.get("adj_open")),
            adj_high=_as_float(data.get("adj_high")),
            adj_low=_as_float(data.get("adj_low")),
            adj_close=_as_float(data.get("adj_close")),
            adj_volume=_as_float(data.get("adj_volume")),
            source=str(data.get("source", "")),
            fetched_at=str(data.get("fetched_at", "")),
            data_source_plan=_as_str_or_none(data.get("data_source_plan")),
            raw_payload_version=_as_str_or_none(data.get("raw_payload_version")),
            updated_at=_as_str_or_none(data.get("updated_at")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "code": self.code,
            "date": self.date,
            "open": self.open_price,
            "high": self.high_price,
            "low": self.low_price,
            "close": self.close_price,
            "volume": self.volume,
            "turnover_value": self.turnover_value,
            "adj_open": self.adj_open,
            "adj_high": self.adj_high,
            "adj_low": self.adj_low,
            "adj_close": self.adj_close,
            "adj_volume": self.adj_volume,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "data_source_plan": self.data_source_plan,
            "raw_payload_version": self.raw_payload_version,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class TechnicalIndicatorsDaily:
    ticker: str
    trade_date: str
    schema_version: int
    calculated_at: str
    values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", normalize_ticker(self.ticker))
        object.__setattr__(self, "trade_date", normalize_trade_date(self.trade_date))
        if int(self.schema_version) <= 0:
            raise ValueError("schema_version must be > 0")
        object.__setattr__(self, "schema_version", int(self.schema_version))
        object.__setattr__(self, "values", _normalize_indicator_values(self.values))

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "TechnicalIndicatorsDaily":
        values = {
            key: data[key]
            for key in TECHNICAL_INDICATOR_FIELD_KEYS
            if key in data
        }
        return cls(
            ticker=str(data["ticker"]),
            trade_date=str(data["trade_date"]),
            schema_version=int(data["schema_version"]),
            calculated_at=str(data.get("calculated_at", "")),
            values=values,
        )

    def to_document(self) -> dict[str, Any]:
        row = {
            "ticker": self.ticker,
            "trade_date": self.trade_date,
            "schema_version": self.schema_version,
            "calculated_at": self.calculated_at,
        }
        row.update(self.values)
        return row

    def get_value(self, field_key: str) -> Any:
        normalized_key = field_key.strip()
        if normalized_key not in TECHNICAL_INDICATOR_FIELD_KEY_SET:
            raise ValueError(f"unsupported technical field_key: {field_key}")
        return self.values.get(normalized_key)


@dataclass(frozen=True)
class TechnicalSyncState:
    ticker: str
    latest_fetched_trade_date: str | None
    latest_calculated_trade_date: str | None
    last_run_at: str
    last_status: str
    last_fetch_from: str | None = None
    last_fetch_to: str | None = None
    last_error: str | None = None
    last_full_refresh_at: str | None = None
    schema_version: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", normalize_ticker(self.ticker))
        object.__setattr__(self, "latest_fetched_trade_date", _normalize_optional_trade_date(self.latest_fetched_trade_date))
        object.__setattr__(
            self,
            "latest_calculated_trade_date",
            _normalize_optional_trade_date(self.latest_calculated_trade_date),
        )
        object.__setattr__(self, "last_fetch_from", _normalize_optional_trade_date(self.last_fetch_from))
        object.__setattr__(self, "last_fetch_to", _normalize_optional_trade_date(self.last_fetch_to))
        object.__setattr__(
            self,
            "last_full_refresh_at",
            _as_str_or_none(self.last_full_refresh_at),
        )
        object.__setattr__(self, "last_error", _as_str_or_none(self.last_error))
        if self.schema_version is not None:
            if int(self.schema_version) <= 0:
                raise ValueError("schema_version must be > 0")
            object.__setattr__(self, "schema_version", int(self.schema_version))

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "TechnicalSyncState":
        return cls(
            ticker=str(data["ticker"]),
            latest_fetched_trade_date=_as_str_or_none(data.get("latest_fetched_trade_date")),
            latest_calculated_trade_date=_as_str_or_none(data.get("latest_calculated_trade_date")),
            last_run_at=str(data.get("last_run_at", "")),
            last_status=str(data.get("last_status", "")),
            last_fetch_from=_as_str_or_none(data.get("last_fetch_from")),
            last_fetch_to=_as_str_or_none(data.get("last_fetch_to")),
            last_error=_as_str_or_none(data.get("last_error")),
            last_full_refresh_at=_as_str_or_none(data.get("last_full_refresh_at")),
            schema_version=_as_int(data.get("schema_version")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "latest_fetched_trade_date": self.latest_fetched_trade_date,
            "latest_calculated_trade_date": self.latest_calculated_trade_date,
            "last_run_at": self.last_run_at,
            "last_status": self.last_status,
            "last_fetch_from": self.last_fetch_from,
            "last_fetch_to": self.last_fetch_to,
            "last_error": self.last_error,
            "last_full_refresh_at": self.last_full_refresh_at,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class TechnicalAlertRule:
    rule_id: str
    ticker: str
    rule_name: str
    field_key: str
    operator: TechnicalAlertOperator
    threshold_value: float | None = None
    threshold_upper: float | None = None
    is_active: bool = True
    note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", normalize_rule_id(self.rule_id))
        object.__setattr__(self, "ticker", normalize_ticker(self.ticker))
        rule_name = str(self.rule_name).strip()
        if not rule_name:
            raise ValueError("rule_name is required")
        object.__setattr__(self, "rule_name", rule_name)
        object.__setattr__(self, "field_key", _normalize_field_key(self.field_key))
        _validate_rule_thresholds(
            operator=self.operator,
            threshold_value=self.threshold_value,
            threshold_upper=self.threshold_upper,
        )
        object.__setattr__(self, "is_active", _as_bool(self.is_active, default=True))
        object.__setattr__(self, "note", _as_str_or_none(self.note))
        object.__setattr__(self, "created_at", _as_str_or_none(self.created_at))
        object.__setattr__(self, "updated_at", _as_str_or_none(self.updated_at))

    @classmethod
    def create(
        cls,
        *,
        ticker: str,
        rule_name: str,
        field_key: str,
        operator: TechnicalAlertOperator,
        threshold_value: float | None = None,
        threshold_upper: float | None = None,
        is_active: bool = True,
        note: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        rule_id: str | None = None,
    ) -> "TechnicalAlertRule":
        return cls(
            rule_id=rule_id or uuid.uuid4().hex,
            ticker=ticker,
            rule_name=rule_name,
            field_key=field_key,
            operator=operator,
            threshold_value=threshold_value,
            threshold_upper=threshold_upper,
            is_active=is_active,
            note=note,
            created_at=created_at,
            updated_at=updated_at,
        )

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "TechnicalAlertRule":
        return cls(
            rule_id=str(data["rule_id"]),
            ticker=str(data["ticker"]),
            rule_name=str(data["rule_name"]),
            field_key=str(data["field_key"]),
            operator=TechnicalAlertOperator(str(data["operator"]).strip().upper()),
            threshold_value=_as_float(data.get("threshold_value")),
            threshold_upper=_as_float(data.get("threshold_upper")),
            is_active=_as_bool(data.get("is_active"), default=True),
            note=_as_str_or_none(data.get("note")),
            created_at=_as_str_or_none(data.get("created_at")),
            updated_at=_as_str_or_none(data.get("updated_at")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "ticker": self.ticker,
            "rule_name": self.rule_name,
            "field_key": self.field_key,
            "operator": self.operator.value,
            "threshold_value": self.threshold_value,
            "threshold_upper": self.threshold_upper,
            "is_active": self.is_active,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class TechnicalAlertState:
    ticker: str
    rule_id: str
    last_evaluated_trade_date: str | None
    last_condition_met: bool
    last_triggered_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", normalize_ticker(self.ticker))
        object.__setattr__(self, "rule_id", normalize_rule_id(self.rule_id))
        object.__setattr__(
            self,
            "last_evaluated_trade_date",
            _normalize_optional_trade_date(self.last_evaluated_trade_date),
        )
        object.__setattr__(self, "last_triggered_at", _as_str_or_none(self.last_triggered_at))
        object.__setattr__(self, "updated_at", _as_str_or_none(self.updated_at))
        object.__setattr__(self, "last_condition_met", _as_bool(self.last_condition_met, default=False))

    @classmethod
    def from_document(cls, data: dict[str, Any]) -> "TechnicalAlertState":
        return cls(
            ticker=str(data["ticker"]),
            rule_id=str(data["rule_id"]),
            last_evaluated_trade_date=_as_str_or_none(data.get("last_evaluated_trade_date")),
            last_condition_met=_as_bool(data.get("last_condition_met"), default=False),
            last_triggered_at=_as_str_or_none(data.get("last_triggered_at")),
            updated_at=_as_str_or_none(data.get("updated_at")),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "rule_id": self.rule_id,
            "last_evaluated_trade_date": self.last_evaluated_trade_date,
            "last_condition_met": self.last_condition_met,
            "last_triggered_at": self.last_triggered_at,
            "updated_at": self.updated_at,
        }


class PriceBarDailyRepository(Protocol):
    def get(self, ticker: str, trade_date: str) -> PriceBarDaily | None:
        """Get single daily bar."""

    def upsert(self, bar: PriceBarDaily) -> None:
        """Persist daily bar."""

    def list_recent(self, ticker: str, *, limit: int) -> list[PriceBarDaily]:
        """Get recent bars."""


class TechnicalIndicatorsDailyRepository(Protocol):
    def get(self, ticker: str, trade_date: str) -> TechnicalIndicatorsDaily | None:
        """Get single indicator row."""

    def upsert(self, indicators: TechnicalIndicatorsDaily) -> None:
        """Persist indicator row."""

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalIndicatorsDaily]:
        """Get recent indicator rows."""


class TechnicalSyncStateRepository(Protocol):
    def get(self, ticker: str) -> TechnicalSyncState | None:
        """Get sync state by ticker."""

    def upsert(self, state: TechnicalSyncState) -> None:
        """Persist sync state."""

    def list_recent(self, *, limit: int) -> list[TechnicalSyncState]:
        """List recent sync states."""


class TechnicalAlertRulesRepository(Protocol):
    def get(self, ticker: str, rule_id: str) -> TechnicalAlertRule | None:
        """Get alert rule."""

    def upsert(self, rule: TechnicalAlertRule) -> None:
        """Persist alert rule."""

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalAlertRule]:
        """List recent alert rules for ticker."""


class TechnicalAlertStateRepository(Protocol):
    def get(self, ticker: str, rule_id: str) -> TechnicalAlertState | None:
        """Get alert state."""

    def upsert(self, state: TechnicalAlertState) -> None:
        """Persist alert state."""

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalAlertState]:
        """List recent alert states for ticker."""


def normalize_rule_id(rule_id: str) -> str:
    normalized = str(rule_id).strip()
    if not normalized:
        raise ValueError("rule_id is required")
    if "|" in normalized:
        raise ValueError("rule_id must not contain '|'.")
    return normalized


def _normalize_indicator_values(values: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        normalized_key = _normalize_field_key(key)
        if normalized_key in TECHNICAL_INDICATOR_FLOAT_FIELD_SET:
            normalized[normalized_key] = _as_float(value)
        elif normalized_key in TECHNICAL_INDICATOR_INT_FIELD_SET:
            normalized[normalized_key] = _as_int(value)
        elif normalized_key in TECHNICAL_INDICATOR_BOOL_FIELD_SET:
            normalized[normalized_key] = _as_bool_or_none(value)
        elif normalized_key in TECHNICAL_INDICATOR_STRING_FIELD_SET:
            normalized[normalized_key] = _as_str_or_none(value)
        else:  # pragma: no cover
            raise ValueError(f"unsupported technical field_key: {key}")
    return normalized


def _normalize_field_key(field_key: str) -> str:
    normalized = str(field_key).strip()
    if normalized not in TECHNICAL_INDICATOR_FIELD_KEY_SET:
        raise ValueError(f"unsupported technical field_key: {field_key}")
    return normalized


def _validate_rule_thresholds(
    *,
    operator: TechnicalAlertOperator,
    threshold_value: float | None,
    threshold_upper: float | None,
) -> None:
    if operator in {TechnicalAlertOperator.IS_TRUE, TechnicalAlertOperator.IS_FALSE}:
        if threshold_value is not None or threshold_upper is not None:
            raise ValueError(f"{operator.value} does not accept threshold values.")
        return
    if operator in {TechnicalAlertOperator.GTE, TechnicalAlertOperator.LTE}:
        if threshold_value is None:
            raise ValueError(f"{operator.value} requires threshold_value.")
        if threshold_upper is not None:
            raise ValueError(f"{operator.value} does not accept threshold_upper.")
        return
    if threshold_value is None or threshold_upper is None:
        raise ValueError(f"{operator.value} requires threshold_value and threshold_upper.")
    if threshold_value > threshold_upper:
        raise ValueError("threshold_value must be <= threshold_upper.")


def _normalize_optional_trade_date(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return normalize_trade_date(text)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("bool is not accepted as float.")
    return float(value)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("bool is not accepted as int.")
    return int(value)


def _as_bool(value: Any, *, default: bool) -> bool:
    parsed = _as_bool_or_none(value)
    if parsed is None:
        return default
    return parsed


def _as_bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in {0, 0.0}:
            return False
        if value in {1, 1.0}:
            return True
    text = str(value).strip().lower()
    if text in {"true", "1"}:
        return True
    if text in {"false", "0"}:
        return False
    raise ValueError(f"invalid bool value: {value}")


def _as_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kabu_per_bot.technical import (
    TECHNICAL_INDICATOR_BOOL_FIELD_SET,
    TECHNICAL_INDICATOR_FLOAT_FIELD_SET,
    TECHNICAL_INDICATOR_INT_FIELD_SET,
    TechnicalAlertOperator,
    TechnicalAlertRule,
    TechnicalAlertState,
    TechnicalIndicatorsDaily,
)


NUMERIC_FIELD_KEYS = frozenset((*TECHNICAL_INDICATOR_FLOAT_FIELD_SET, *TECHNICAL_INDICATOR_INT_FIELD_SET))


@dataclass(frozen=True)
class TechnicalAlertEvaluation:
    rule: TechnicalAlertRule
    trade_date: str
    current_value: Any
    previous_value: Any
    condition_met: bool
    previous_condition_met: bool | None
    should_trigger: bool
    invalid_reason: str | None = None

    @property
    def is_supported(self) -> bool:
        return self.invalid_reason is None


def evaluate_technical_alert_rule(
    *,
    rule: TechnicalAlertRule,
    current: TechnicalIndicatorsDaily,
    previous: TechnicalIndicatorsDaily | None,
    previous_state: TechnicalAlertState | None = None,
) -> TechnicalAlertEvaluation:
    current_value = current.get_value(rule.field_key)
    previous_value = previous.get_value(rule.field_key) if previous is not None else None
    invalid_reason = _resolve_invalid_reason(rule=rule)
    if invalid_reason is not None:
        return TechnicalAlertEvaluation(
            rule=rule,
            trade_date=current.trade_date,
            current_value=current_value,
            previous_value=previous_value,
            condition_met=False,
            previous_condition_met=None,
            should_trigger=False,
            invalid_reason=invalid_reason,
        )

    condition_met = _evaluate_condition(value=current_value, rule=rule)
    previous_condition_met = _resolve_previous_condition_met(
        rule=rule,
        current=current,
        previous=previous,
        previous_state=previous_state,
    )
    should_trigger = _resolve_should_trigger(
        rule=rule,
        condition_met=condition_met,
        previous_condition_met=previous_condition_met,
    )
    return TechnicalAlertEvaluation(
        rule=rule,
        trade_date=current.trade_date,
        current_value=current_value,
        previous_value=previous_value,
        condition_met=condition_met,
        previous_condition_met=previous_condition_met,
        should_trigger=should_trigger,
    )


def build_technical_alert_state(
    *,
    evaluation: TechnicalAlertEvaluation,
    previous_state: TechnicalAlertState | None,
    updated_at: str,
    last_triggered_at: str | None = None,
) -> TechnicalAlertState:
    if previous_state is not None and last_triggered_at is None:
        last_triggered_at = previous_state.last_triggered_at
    return TechnicalAlertState(
        ticker=evaluation.rule.ticker,
        rule_id=evaluation.rule.rule_id,
        last_evaluated_trade_date=evaluation.trade_date,
        last_condition_met=evaluation.condition_met,
        last_triggered_at=last_triggered_at,
        updated_at=updated_at,
    )


def describe_technical_alert_threshold(rule: TechnicalAlertRule) -> str:
    if rule.operator is TechnicalAlertOperator.IS_TRUE:
        return "TRUE"
    if rule.operator is TechnicalAlertOperator.IS_FALSE:
        return "FALSE"
    if rule.operator is TechnicalAlertOperator.GTE:
        return f">= {_fmt_number(rule.threshold_value)}"
    if rule.operator is TechnicalAlertOperator.LTE:
        return f"<= {_fmt_number(rule.threshold_value)}"
    if rule.operator is TechnicalAlertOperator.BETWEEN:
        return f"{_fmt_number(rule.threshold_value)} - {_fmt_number(rule.threshold_upper)}"
    return f"< {_fmt_number(rule.threshold_value)} または > {_fmt_number(rule.threshold_upper)}"


def _resolve_invalid_reason(*, rule: TechnicalAlertRule) -> str | None:
    if rule.operator in {TechnicalAlertOperator.IS_TRUE, TechnicalAlertOperator.IS_FALSE}:
        if rule.field_key not in TECHNICAL_INDICATOR_BOOL_FIELD_SET:
            return "boolean operator requires bool field_key"
        return None
    if rule.field_key not in NUMERIC_FIELD_KEYS:
        return "numeric operator requires numeric field_key"
    return None


def _resolve_previous_condition_met(
    *,
    rule: TechnicalAlertRule,
    current: TechnicalIndicatorsDaily,
    previous: TechnicalIndicatorsDaily | None,
    previous_state: TechnicalAlertState | None,
) -> bool | None:
    if previous_state is not None and previous_state.last_evaluated_trade_date == current.trade_date:
        return previous_state.last_condition_met
    if previous is not None and previous.trade_date < current.trade_date:
        return _evaluate_condition(value=previous.get_value(rule.field_key), rule=rule)
    if previous_state is not None and previous_state.last_evaluated_trade_date is not None:
        if previous_state.last_evaluated_trade_date < current.trade_date:
            return previous_state.last_condition_met
    return None


def _resolve_should_trigger(
    *,
    rule: TechnicalAlertRule,
    condition_met: bool,
    previous_condition_met: bool | None,
) -> bool:
    if not condition_met:
        return False
    if previous_condition_met is None:
        return rule.operator in {TechnicalAlertOperator.IS_TRUE, TechnicalAlertOperator.IS_FALSE}
    return not previous_condition_met


def _evaluate_condition(*, value: Any, rule: TechnicalAlertRule) -> bool:
    if rule.operator is TechnicalAlertOperator.IS_TRUE:
        return value is True
    if rule.operator is TechnicalAlertOperator.IS_FALSE:
        return value is False
    if value is None:
        return False
    number = float(value)
    lower = float(rule.threshold_value) if rule.threshold_value is not None else None
    upper = float(rule.threshold_upper) if rule.threshold_upper is not None else None
    if rule.operator is TechnicalAlertOperator.GTE:
        return number >= float(lower)
    if rule.operator is TechnicalAlertOperator.LTE:
        return number <= float(lower)
    if rule.operator is TechnicalAlertOperator.BETWEEN:
        return float(lower) <= number <= float(upper)
    if rule.operator is TechnicalAlertOperator.OUTSIDE:
        return number < float(lower) or number > float(upper)
    raise ValueError(f"unsupported operator: {rule.operator}")


def _fmt_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"

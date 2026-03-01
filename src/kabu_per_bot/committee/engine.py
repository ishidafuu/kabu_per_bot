from __future__ import annotations

from statistics import mean

from kabu_per_bot.committee.base import CommitteeLens
from kabu_per_bot.committee.lens_business import BusinessLens
from kabu_per_bot.committee.lens_event import EventLens
from kabu_per_bot.committee.lens_financial import FinancialLens
from kabu_per_bot.committee.lens_risk import RiskLens
from kabu_per_bot.committee.lens_technical import TechnicalLens
from kabu_per_bot.committee.lens_valuation import ValuationLens
from kabu_per_bot.committee.types import CommitteeContext, CommitteeEvaluation, LensDirection, clamp_score


class CommitteeEvaluationEngine:
    def __init__(self, lenses: tuple[CommitteeLens, ...] | None = None) -> None:
        self._lenses = lenses or (
            BusinessLens(),
            FinancialLens(),
            ValuationLens(),
            TechnicalLens(),
            EventLens(),
            RiskLens(),
        )

    def evaluate(self, context: CommitteeContext) -> CommitteeEvaluation:
        lens_results = tuple(lens.evaluate(context) for lens in self._lenses)
        missing_fields: list[str] = []
        for result in lens_results:
            missing_fields.extend(result.missing_fields)

        confidence_values = [result.confidence for result in lens_results]
        strength_values = [result.strength for result in lens_results]
        confidence = int(round(mean(confidence_values))) if confidence_values else 1
        strength = int(round(max(strength_values))) if strength_values else 1

        directions = {result.direction for result in lens_results}
        if LensDirection.POSITIVE in directions and LensDirection.NEGATIVE in directions:
            confidence -= 1
        if len(set(missing_fields)) >= 3:
            confidence -= 1
            strength = max(strength, 4)

        return CommitteeEvaluation(
            ticker=context.ticker,
            company_name=context.company_name,
            trade_date=context.trade_date,
            confidence=clamp_score(confidence),
            strength=clamp_score(strength),
            lenses=lens_results,
            missing_fields=tuple(dict.fromkeys(missing_fields)),
        )

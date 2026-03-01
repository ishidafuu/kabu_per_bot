from __future__ import annotations

from kabu_per_bot.committee.types import CommitteeContext, LensDirection, LensEvaluation, LensKey


class BusinessLens:
    key = LensKey.BUSINESS.value
    title = "事業"

    def evaluate(self, context: CommitteeContext) -> LensEvaluation:
        baseline = context.baseline_summary or {}
        summary = str(baseline.get("business_summary", "")).strip()
        growth = str(baseline.get("growth_driver", "")).strip()
        risk = str(baseline.get("business_risk", "")).strip()

        lines: list[str] = []
        missing_fields: list[str] = []

        if summary:
            lines.append(f"主軸: {summary}")
        else:
            lines.append("主軸: 基礎調査データが不足しています。")
            missing_fields.append("business_summary")

        if growth:
            lines.append(f"成長要因: {growth}")
        else:
            lines.append("成長要因: 月次基礎調査の更新待ちです。")
            missing_fields.append("growth_driver")

        direction = LensDirection.NEUTRAL
        strength = 2
        confidence = 2

        if risk:
            lines.append(f"懸念: {risk}")
            direction = LensDirection.NEGATIVE
            strength = 4
            confidence = 3
        elif summary and growth:
            direction = LensDirection.POSITIVE
            strength = 3
            confidence = 4

        if context.baseline_reliability_score is not None:
            confidence = min(5, max(1, context.baseline_reliability_score))

        return LensEvaluation(
            key=LensKey.BUSINESS,
            title=self.title,
            direction=direction,
            confidence=confidence,
            strength=strength,
            lines=tuple(lines),
            missing_fields=tuple(missing_fields),
        )

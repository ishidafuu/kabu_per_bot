from __future__ import annotations

from kabu_per_bot.committee.types import CommitteeContext, LensDirection, LensEvaluation, LensKey


class RiskLens:
    key = LensKey.RISK.value
    title = "リスク"

    def evaluate(self, context: CommitteeContext) -> LensEvaluation:
        missing_fields: list[str] = []
        lines: list[str] = []
        strength = 2
        confidence = 4
        direction = LensDirection.NEUTRAL

        if context.market_snapshot is None:
            missing_fields.append("market_snapshot")
        else:
            missing_fields.extend(context.market_snapshot.missing_fields())

        if context.latest_metric is None:
            missing_fields.append("latest_metric")
        else:
            missing_fields.extend(context.latest_metric.missing_fields(metric_type=context.metric_type))

        if context.latest_medians is None:
            missing_fields.append("metric_medians")
        else:
            insufficient = context.latest_medians.insufficient_windows()
            missing_fields.extend([f"median_{key.lower()}" for key in insufficient])

        unique_missing = tuple(dict.fromkeys(missing_fields))
        if unique_missing:
            lines.append(f"欠損: {', '.join(unique_missing[:4])}")
            direction = LensDirection.NEGATIVE
            strength = 4
            confidence = 3
        else:
            lines.append("欠損: 主要項目は取得済みです。")

        day_change = context.day_change_pct
        week_change = context.week_change_pct
        if day_change is not None and abs(day_change) >= 4.0:
            lines.append(f"日次変動: {day_change:+.1f}%（警戒帯）")
            direction = LensDirection.NEGATIVE
            strength = max(strength, 4)
        elif day_change is not None:
            lines.append(f"日次変動: {day_change:+.1f}%")
        else:
            lines.append("日次変動: 算出不可")
            confidence = min(confidence, 3)

        if week_change is not None and abs(week_change) >= 8.0:
            lines.append(f"週次変動: {week_change:+.1f}%（高変動）")
            direction = LensDirection.NEGATIVE
            strength = max(strength, 5)
        elif week_change is not None:
            lines.append(f"週次変動: {week_change:+.1f}%")
        else:
            lines.append("週次変動: 算出不可")
            confidence = min(confidence, 3)

        return LensEvaluation(
            key=LensKey.RISK,
            title=self.title,
            direction=direction,
            confidence=confidence,
            strength=strength,
            lines=tuple(lines),
            missing_fields=unique_missing,
        )

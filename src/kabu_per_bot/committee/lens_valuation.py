from __future__ import annotations

from kabu_per_bot.committee.types import CommitteeContext, LensDirection, LensEvaluation, LensKey


class ValuationLens:
    key = LensKey.VALUATION.value
    title = "バリュ"

    def evaluate(self, context: CommitteeContext) -> LensEvaluation:
        value = context.metric_value()
        medians = context.latest_medians
        metric_label = context.metric_type.value

        lines: list[str] = []
        missing_fields: list[str] = []
        direction = LensDirection.NEUTRAL
        confidence = 2
        strength = 2

        if value is None:
            lines.append(f"{metric_label}: 直近値が欠損しています。")
            missing_fields.append("metric_value")
            return LensEvaluation(
                key=LensKey.VALUATION,
                title=self.title,
                direction=LensDirection.NEGATIVE,
                confidence=1,
                strength=4,
                lines=tuple(lines),
                missing_fields=tuple(missing_fields),
            )

        lines.append(f"{metric_label}: {value:.2f}")
        if medians is None:
            lines.append("中央値: 1W/3M/1Y が未計算です。")
            missing_fields.append("metric_medians")
            return LensEvaluation(
                key=LensKey.VALUATION,
                title=self.title,
                direction=direction,
                confidence=1,
                strength=2,
                lines=tuple(lines),
                missing_fields=tuple(missing_fields),
            )

        m1 = medians.median_1w
        m3 = medians.median_3m
        m12 = medians.median_1y
        lines.append(
            f"中央値(1W/3M/1Y): {_fmt(m1)} / {_fmt(m3)} / {_fmt(m12)}"
        )

        under_count = 0
        available_windows = 0
        for median in (m1, m3, m12):
            if median is None:
                continue
            available_windows += 1
            if value < median:
                under_count += 1
        if available_windows == 0:
            lines.append("判定: 比較可能な中央値がありません。")
            confidence = 1
            missing_fields.append("median_1w")
            missing_fields.append("median_3m")
            missing_fields.append("median_1y")
        else:
            lines.append(f"判定: {available_windows}窓中 {under_count}窓で割安側。")
            confidence = min(5, 1 + available_windows)
            if under_count >= 2:
                direction = LensDirection.POSITIVE
                strength = 4 if under_count == available_windows else 3
            elif under_count == 0:
                direction = LensDirection.NEGATIVE
                strength = 3

        return LensEvaluation(
            key=LensKey.VALUATION,
            title=self.title,
            direction=direction,
            confidence=confidence,
            strength=strength,
            lines=tuple(lines),
            missing_fields=tuple(dict.fromkeys(missing_fields)),
        )


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"

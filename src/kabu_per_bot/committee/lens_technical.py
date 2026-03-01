from __future__ import annotations

from kabu_per_bot.committee.types import CommitteeContext, LensDirection, LensEvaluation, LensKey


class TechnicalLens:
    key = LensKey.TECHNICAL.value
    title = "テクニカル"

    def evaluate(self, context: CommitteeContext) -> LensEvaluation:
        day_change = context.day_change_pct
        week_change = context.week_change_pct
        ma20 = context.moving_average(20)
        ma60 = context.moving_average(60)
        latest_close = context.recent_metrics[0].close_price if context.recent_metrics else None

        lines: list[str] = []
        missing_fields: list[str] = []
        direction = LensDirection.NEUTRAL
        confidence = 3
        strength = 2

        if latest_close is None:
            lines.append("終値: 直近の終値が不足しています。")
            missing_fields.append("close_price")
            return LensEvaluation(
                key=LensKey.TECHNICAL,
                title=self.title,
                direction=LensDirection.NEGATIVE,
                confidence=1,
                strength=4,
                lines=tuple(lines),
                missing_fields=tuple(missing_fields),
            )

        lines.append(f"騰落率(日/週): {_pct(day_change)} / {_pct(week_change)}")
        lines.append(f"移動平均(20/60): {_num(ma20)} / {_num(ma60)}")

        if ma20 is None or ma60 is None:
            missing_fields.append("moving_average")
            lines.append("トレンド: 履歴不足で判定精度が下がっています。")
            confidence = 2
        else:
            bullish = latest_close >= ma20 >= ma60
            bearish = latest_close <= ma20 <= ma60
            if bullish:
                lines.append("トレンド: 上向き基調。")
                direction = LensDirection.POSITIVE
                strength = 3
            elif bearish:
                lines.append("トレンド: 下向き基調。")
                direction = LensDirection.NEGATIVE
                strength = 4
            else:
                lines.append("トレンド: 方向感は中立。")

        if day_change is not None and abs(day_change) >= 4.0:
            direction = LensDirection.NEGATIVE
            strength = max(strength, 4)
            confidence = min(confidence, 3)
        if week_change is not None and abs(week_change) >= 8.0:
            direction = LensDirection.NEGATIVE
            strength = max(strength, 5)
            confidence = min(confidence, 3)

        return LensEvaluation(
            key=LensKey.TECHNICAL,
            title=self.title,
            direction=direction,
            confidence=confidence,
            strength=strength,
            lines=tuple(lines),
            missing_fields=tuple(missing_fields),
        )


def _pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.1f}%"


def _num(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"

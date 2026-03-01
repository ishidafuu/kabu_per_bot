from __future__ import annotations

from kabu_per_bot.committee.types import CommitteeContext, LensDirection, LensEvaluation, LensKey


class EventLens:
    key = LensKey.EVENT.value
    title = "イベント"

    def evaluate(self, context: CommitteeContext) -> LensEvaluation:
        earnings_days = context.earnings_days
        snapshot = context.market_snapshot
        lines: list[str] = []
        missing_fields: list[str] = []
        direction = LensDirection.NEUTRAL
        confidence = 3
        strength = 2

        if earnings_days is None:
            lines.append("決算: 次回決算日が不明です。")
            missing_fields.append("earnings_date")
            direction = LensDirection.NEGATIVE
            strength = 4
            confidence = 2
        else:
            lines.append(f"決算まで: {earnings_days}日")
            if earnings_days <= 5:
                lines.append("直前イベント帯: 変動リスクが高く静観寄り。")
                direction = LensDirection.NEGATIVE
                strength = 5
            elif earnings_days <= 10:
                lines.append("イベント接近: 新規判断は段階的に。")
                direction = LensDirection.NEGATIVE
                strength = 4
            elif earnings_days <= 15:
                lines.append("注意帯: 追加情報の確認優先。")
                strength = 3
            else:
                lines.append("イベント距離: 直近イベント圧力は限定的。")

        if snapshot is None:
            lines.append("市場スナップショット: 取得失敗。")
            missing_fields.append("market_snapshot")
            confidence = 1
        else:
            lines.append(f"取得源: {snapshot.source}")

        return LensEvaluation(
            key=LensKey.EVENT,
            title=self.title,
            direction=direction,
            confidence=confidence,
            strength=strength,
            lines=tuple(lines),
            missing_fields=tuple(dict.fromkeys(missing_fields)),
        )

from __future__ import annotations

from kabu_per_bot.committee.types import CommitteeContext, LensDirection, LensEvaluation, LensKey


class FinancialLens:
    key = LensKey.FINANCIAL.value
    title = "財務"

    def evaluate(self, context: CommitteeContext) -> LensEvaluation:
        baseline = context.baseline_summary or {}
        debt_comment = str(baseline.get("debt_comment", "")).strip()
        cf_comment = str(baseline.get("cf_comment", "")).strip()

        lines: list[str] = []
        missing_fields: list[str] = []
        direction = LensDirection.NEUTRAL
        confidence = 2
        strength = 2

        if debt_comment:
            lines.append(f"負債: {debt_comment}")
        else:
            lines.append("負債: 基礎調査データが不足しています。")
            missing_fields.append("debt_comment")

        if cf_comment:
            lines.append(f"CF: {cf_comment}")
        else:
            lines.append("CF: 月次基礎調査の更新待ちです。")
            missing_fields.append("cf_comment")

        snapshot = context.market_snapshot
        if snapshot is None:
            lines.append("速報値: 市場データ未取得です。")
            missing_fields.append("market_snapshot")
            direction = LensDirection.NEGATIVE
            strength = 4
        else:
            if snapshot.eps_forecast is None and snapshot.sales_forecast is None:
                lines.append("速報値: 予想EPS/売上予想が欠損しています。")
                missing_fields.append("eps_forecast")
                missing_fields.append("sales_forecast")
                direction = LensDirection.NEGATIVE
                strength = 4
            elif snapshot.eps_forecast is not None and snapshot.eps_forecast > 0:
                lines.append(f"速報値: 予想EPS={snapshot.eps_forecast:.2f}")
                direction = LensDirection.POSITIVE if direction is not LensDirection.NEGATIVE else direction
                strength = max(strength, 3)
                confidence = 3
            elif snapshot.sales_forecast is not None and snapshot.sales_forecast > 0:
                lines.append(f"速報値: 売上予想={snapshot.sales_forecast:.2f}")
                strength = max(strength, 3)
                confidence = 3
            else:
                lines.append("速報値: 予想値の解釈が難しい状態です。")
                direction = LensDirection.NEGATIVE
                strength = max(strength, 3)

        return LensEvaluation(
            key=LensKey.FINANCIAL,
            title=self.title,
            direction=direction,
            confidence=confidence,
            strength=strength,
            lines=tuple(lines),
            missing_fields=tuple(dict.fromkeys(missing_fields)),
        )

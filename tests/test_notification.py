from __future__ import annotations

import unittest

from kabu_per_bot.intelligence import AiInsight, IntelEvent, IntelKind
from kabu_per_bot.notification import (
    format_ai_attention_message,
    format_committee_evaluation_message,
    format_data_unknown_message,
    format_earnings_message,
    format_intel_update_message,
    format_signal_message,
    format_signal_status_message,
    format_technical_alert_message,
)
from kabu_per_bot.committee.types import CommitteeEvaluation, LensDirection, LensEvaluation, LensKey
from kabu_per_bot.signal import SignalState
from kabu_per_bot.watchlist import MetricType


class NotificationFormatterTest(unittest.TestCase):
    def test_signal_message_format(self) -> None:
        state = SignalState(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            metric_value=10.0,
            under_1w=True,
            under_3m=True,
            under_1y=True,
            combo="1Y+3M+1W",
            is_strong=True,
            category="超PER割安",
            streak_days=3,
            updated_at="2026-02-12T00:00:00+00:00",
        )
        message = format_signal_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            state=state,
            signal_phase="新規",
            metric_value=10.0,
            median_1w=12.0,
            median_3m=13.0,
            median_1y=14.0,
        )
        self.assertIn("🔥 優先度:高 / 推奨アクション:優先確認 / 根拠数値:PER=10.00", message.body)
        self.assertIn("区分: [新規] 超PER割安", message.body)
        self.assertIn("under（3日連続）", message.body)
        self.assertIn("差分(現在-中央値): 1W -2.00 / 3M -3.00 / 1Y -4.00", message.body)
        self.assertIn("乖離率: 1W -16.7% / 3M -23.1% / 1Y -28.6%", message.body)
        self.assertIn("🔥", message.body)
        self.assertEqual(message.category, "超PER割安")

    def test_signal_message_includes_earnings_days(self) -> None:
        state = SignalState(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            metric_value=10.0,
            under_1w=True,
            under_3m=True,
            under_1y=True,
            combo="1Y+3M+1W",
            is_strong=True,
            category="超PER割安",
            streak_days=3,
            updated_at="2026-02-12T00:00:00+00:00",
        )
        message = format_signal_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            state=state,
            signal_phase="新規",
            metric_value=10.0,
            median_1w=12.0,
            median_3m=13.0,
            median_1y=14.0,
            earnings_days=2,
        )
        self.assertIn("📅 決算まで: 2日", message.body)

    def test_earnings_message_format(self) -> None:
        message = format_earnings_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            earnings_date="2026-02-13",
            earnings_time="15:00",
            category="明日決算",
        )
        self.assertIn("【明日決算】", message.body)
        self.assertIn("2026-02-13 15:00", message.body)

    def test_signal_status_message_format(self) -> None:
        state = SignalState(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            metric_value=16.0,
            under_1w=False,
            under_3m=False,
            under_1y=False,
            combo=None,
            is_strong=False,
            category=None,
            streak_days=0,
            updated_at="2026-02-12T00:00:00+00:00",
        )
        message = format_signal_status_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            state=state,
            metric_value=16.0,
            median_1w=12.0,
            median_3m=13.0,
            median_1y=14.0,
            signal_phase="解除",
        )
        self.assertIn("📘 優先度:中 / 推奨アクション:通常監視へ移行 / 根拠数値:PER=16.00", message.body)
        self.assertIn("　PER状況", message.body)
        self.assertIn("シグナル種別: 解除", message.body)
        self.assertIn("差分(現在-中央値): 1W +4.00 / 3M +3.00 / 1Y +2.00", message.body)
        self.assertIn("乖離率: 1W +33.3% / 3M +23.1% / 1Y +14.3%", message.body)
        self.assertIn("判定レベル: 下回りなし", message.body)
        self.assertEqual(message.category, "PER状況")

    def test_signal_status_message_format_with_insufficient_windows(self) -> None:
        state = SignalState(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            metric_value=16.0,
            under_1w=False,
            under_3m=False,
            under_1y=False,
            combo=None,
            is_strong=False,
            category=None,
            streak_days=0,
            updated_at="2026-02-12T00:00:00+00:00",
        )
        message = format_signal_status_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            state=state,
            metric_value=16.0,
            median_1w=None,
            median_3m=13.0,
            median_1y=None,
            insufficient_windows=["1W", "1Y"],
        )
        self.assertIn(
            "📘 優先度:中 / 推奨アクション:データ確認 / 根拠数値:PER=16.00 / 乖離率(1W N/A / 3M +23.1% / 1Y N/A) / 中央値不足(1W/1Y)",
            message.body,
        )
        self.assertIn("判定レベル: 判定不能（中央値不足: 1W/1Y）", message.body)
        self.assertIn("差分(現在-中央値): 1W N/A / 3M +3.00 / 1Y N/A", message.body)
        self.assertIn("乖離率: 1W N/A / 3M +23.1% / 1Y N/A", message.body)
        self.assertIn("割安通知: 判定保留", message.body)
        self.assertEqual(message.condition_key, "PER:STATUS:INSUFFICIENT_1W+1Y")

    def test_signal_status_message_uses_absolute_median_for_divergence_rate(self) -> None:
        state = SignalState(
            ticker="3901:TSE",
            trade_date="2026-02-12",
            metric_type=MetricType.PER,
            metric_value=-5.0,
            under_1w=False,
            under_3m=False,
            under_1y=False,
            combo=None,
            is_strong=False,
            category=None,
            streak_days=0,
            updated_at="2026-02-12T00:00:00+00:00",
        )
        message = format_signal_status_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            state=state,
            metric_value=-5.0,
            median_1w=-10.0,
            median_3m=-8.0,
            median_1y=-6.0,
        )
        self.assertIn("📘 優先度:低 / 推奨アクション:様子見 / 根拠数値:PER=-5.00", message.body)
        self.assertIn("差分(現在-中央値): 1W +5.00 / 3M +3.00 / 1Y +1.00", message.body)
        self.assertIn("乖離率: 1W +50.0% / 3M +37.5% / 1Y +16.7%", message.body)

    def test_data_unknown_message_format(self) -> None:
        message = format_data_unknown_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            missing_fields=["eps_forecast", "close_price"],
            context="日次指標計算",
            earnings_days=0,
        )
        self.assertIn("【データ不明】", message.body)
        self.assertIn("終値/予想EPS", message.body)
        self.assertIn("次の確認:", message.body)
        self.assertIn("📅 決算まで: 当日", message.body)
        self.assertEqual(message.category, "データ不明")

    def test_technical_alert_message_format(self) -> None:
        message = format_technical_alert_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            rule_id="rule-ma25",
            rule_name="25日線回復",
            field_key="close_vs_ma25",
            trade_date="2026-03-08",
            current_value=0.5,
            previous_value=-0.4,
            threshold_label=">= 0.00",
            note="終値ベース",
        )
        self.assertIn("【技術アラート】3901:TSE 富士フイルム", message.body)
        self.assertIn("ルール名: 25日線回復", message.body)
        self.assertIn("現在値: 0.50", message.body)
        self.assertIn("しきい値: >= 0.00", message.body)
        self.assertIn("補助情報: field=close_vs_ma25 / 前回値=-0.40", message.body)
        self.assertIn("メモ: 終値ベース", message.body)
        self.assertEqual(message.condition_key, "TECH:rule-ma25")

    def test_intel_update_message_format(self) -> None:
        message = format_intel_update_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            event=IntelEvent(
                ticker="3901:TSE",
                kind=IntelKind.IR,
                title="決算説明資料を公開",
                url="https://example.com/ir.pdf",
                published_at="2026-02-15T12:00:00+09:00",
                source_label="IRサイト",
                content="決算説明資料を公開しました",
            ),
        )
        self.assertIn("【IR更新】", message.body)
        self.assertIn("📝 ", message.body)
        self.assertIn("URL: https://example.com/ir.pdf", message.body)
        self.assertIn("🏷️ 種別: IRサイト", message.body)
        self.assertNotIn("💬 要約:", message.body)
        self.assertEqual(message.category, "IR更新")

    def test_intel_update_message_format_for_sns_includes_summary(self) -> None:
        message = format_intel_update_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            event=IntelEvent(
                ticker="3901:TSE",
                kind=IntelKind.SNS,
                title="@fujifilm_ir",
                url="https://x.com/fujifilm_ir/status/1",
                published_at="2026-02-15T12:00:00+09:00",
                source_label="公式",
                content="新製品の受注状況と今後の供給見通しを投稿",
            ),
        )
        self.assertIn("🛰️ SNS注目", message.body)
        self.assertIn("投稿: @fujifilm_ir / ソース: 🏢 公式", message.body)
        self.assertIn("要点: 新製品の受注状況と今後の供給見通しを投稿", message.body)
        self.assertIn("🔗 https://x.com/fujifilm_ir/status/1", message.body)
        self.assertNotIn("💬 要約:", message.body)
        self.assertEqual(message.category, "SNS注目")

    def test_intel_update_message_format_for_sns_splits_tagged_summary(self) -> None:
        message = format_intel_update_message(
            ticker="7844:TSE",
            company_name="マーベラス",
            event=IntelEvent(
                ticker="7844:TSE",
                kind=IntelKind.SNS,
                title="@Alpaca_Arcadia",
                url="https://x.com/Alpaca_Arcadia/status/2024302307241066965",
                published_at="2026-02-15T12:00:00+09:00",
                source_label="その他",
                content="[注目度:L|状況:改善|Cat:無|影響:→] 第3Q業績好調でドルウェブ貢献強調。11likes。",
            ),
        )
        self.assertIn("🎯 注目度:L / 状況:改善 / Cat:無 / 影響:→", message.body)
        self.assertIn("要点: 第3Q業績好調でドルウェブ貢献強調。", message.body)
        self.assertIn("投稿: @Alpaca_Arcadia / ソース: 🧩 その他", message.body)
        self.assertNotIn("11likes", message.body)
        self.assertEqual(message.category, "SNS注目")

    def test_ai_attention_message_format(self) -> None:
        message = format_ai_attention_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            event=IntelEvent(
                ticker="3901:TSE",
                kind=IntelKind.SNS,
                title="@fujifilm_ir",
                url="https://x.com/fujifilm_ir/status/1",
                published_at="2026-02-15T12:00:00+09:00",
                source_label="公式",
                content="新製品の受注が好調",
            ),
            insight=AiInsight(
                summary="新製品受注が好調",
                evidence_urls=["https://x.com/fujifilm_ir/status/1"],
                ir_label="該当なし",
                sns_label="公式",
                tone="ポジ",
                confidence="Med",
            ),
        )
        self.assertIn("【AI注目】", message.body)
        self.assertIn("🔗 根拠：", message.body)
        self.assertIn("🏷️ 分類：", message.body)
        self.assertIn("🎯 確信度：", message.body)
        self.assertIn("根拠：https://x.com/fujifilm_ir/status/1", message.body)
        self.assertEqual(message.category, "AI注目")

    def test_committee_evaluation_message_format_with_plain_explanation(self) -> None:
        evaluation = CommitteeEvaluation(
            ticker="9271:TSE",
            company_name="和心",
            trade_date="2026-03-01",
            confidence=2,
            strength=5,
            lenses=(
                LensEvaluation(
                    key=LensKey.BUSINESS,
                    title="事業",
                    direction=LensDirection.NEGATIVE,
                    confidence=2,
                    strength=4,
                    lines=(
                        "主軸: 基礎調査の確認が必要です。",
                        "成長要因: 追加確認中です。",
                        "懸念: 開示が不足しています。",
                    ),
                ),
                LensEvaluation(
                    key=LensKey.RISK,
                    title="リスク",
                    direction=LensDirection.NEGATIVE,
                    confidence=4,
                    strength=5,
                    lines=(
                        "欠損: market_snapshot",
                        "日次変動: +2.9%",
                        "週次変動: +16.8%（高変動）",
                    ),
                ),
            ),
            missing_fields=("market_snapshot",),
        )

        message = format_committee_evaluation_message(evaluation=evaluation)

        self.assertIn("【委員会評価】9271:TSE 和心", message.body)
        self.assertIn("総合: 自信2/5 / 強さ5/5", message.body)
        self.assertIn("見方: 自信=根拠データの十分さ / 強さ=相場シグナルの強さ", message.body)
        self.assertIn("総合コメント:", message.body)
        self.assertIn("欠損データ: market_snapshot", message.body)
        self.assertIn("[事業] 自信2/5 / 強さ4/5 / 方向=ネガ", message.body)
        self.assertIn("理由: 主軸: 基礎調査の確認が必要です。 / 成長要因: 追加確認中です。 / 懸念: 開示が不足しています。", message.body)
        self.assertEqual(message.category, "委員会評価")


if __name__ == "__main__":
    unittest.main()

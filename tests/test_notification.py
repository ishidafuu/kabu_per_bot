from __future__ import annotations

import unittest

from kabu_per_bot.intelligence import AiInsight, IntelEvent, IntelKind
from kabu_per_bot.notification import (
    format_ai_attention_message,
    format_data_unknown_message,
    format_earnings_message,
    format_intel_update_message,
    format_signal_message,
)
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
            metric_value=10.0,
            median_1w=12.0,
            median_3m=13.0,
            median_1y=14.0,
        )
        self.assertIn("【超PER割安】", message.body)
        self.assertIn("連続: 3日", message.body)
        self.assertEqual(message.category, "超PER割安")

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

    def test_data_unknown_message_format(self) -> None:
        message = format_data_unknown_message(
            ticker="3901:TSE",
            company_name="富士フイルム",
            missing_fields=["eps_forecast", "close_price"],
            context="日次指標計算",
        )
        self.assertIn("【データ不明】", message.body)
        self.assertIn("close_price, eps_forecast", message.body)
        self.assertEqual(message.category, "データ不明")

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
        self.assertIn("URL: https://example.com/ir.pdf", message.body)
        self.assertEqual(message.category, "IR更新")

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
        self.assertIn("根拠：https://x.com/fujifilm_ir/status/1", message.body)
        self.assertEqual(message.category, "AI注目")


if __name__ == "__main__":
    unittest.main()

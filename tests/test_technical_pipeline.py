from __future__ import annotations

from dataclasses import dataclass, field
import unittest

from kabu_per_bot.pipeline import NotificationExecutionMode
from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.technical import (
    TechnicalAlertOperator,
    TechnicalAlertRule,
    TechnicalAlertState,
    TechnicalIndicatorsDaily,
)
from kabu_per_bot.technical_profiles import TechnicalProfile, TechnicalProfileType
from kabu_per_bot.technical_pipeline import TechnicalAlertPipelineConfig, run_technical_alert_pipeline
from kabu_per_bot.watchlist import MetricType, NotifyChannel, NotifyTiming, WatchlistItem


@dataclass
class InMemoryTechnicalIndicatorsRepo:
    rows: list[TechnicalIndicatorsDaily] = field(default_factory=list)

    def get(self, ticker: str, trade_date: str) -> TechnicalIndicatorsDaily | None:
        for row in self.rows:
            if row.ticker == ticker and row.trade_date == trade_date:
                return row
        return None

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalIndicatorsDaily]:
        values = [row for row in self.rows if row.ticker == ticker]
        values.sort(key=lambda row: row.trade_date, reverse=True)
        return values[:limit]


@dataclass
class InMemoryTechnicalAlertRulesRepo:
    rows: list[TechnicalAlertRule] = field(default_factory=list)

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalAlertRule]:
        values = [row for row in self.rows if row.ticker == ticker]
        values.sort(key=lambda row: row.updated_at or row.created_at or "", reverse=True)
        return values[:limit]


@dataclass
class InMemoryTechnicalAlertStateRepo:
    rows: list[TechnicalAlertState] = field(default_factory=list)

    def get(self, ticker: str, rule_id: str) -> TechnicalAlertState | None:
        for row in self.rows:
            if row.ticker == ticker and row.rule_id == rule_id:
                return row
        return None

    def upsert(self, state: TechnicalAlertState) -> None:
        self.rows = [
            row
            for row in self.rows
            if not (row.ticker == state.ticker and row.rule_id == state.rule_id)
        ]
        self.rows.append(state)


@dataclass
class InMemoryNotificationLogRepo:
    rows: list[NotificationLogEntry] = field(default_factory=list)

    def append(self, entry: NotificationLogEntry) -> None:
        self.rows.append(entry)

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        values = [row for row in self.rows if row.ticker == ticker]
        values.sort(key=lambda row: row.sent_at, reverse=True)
        return values[:limit]


@dataclass
class InMemoryTechnicalProfilesRepo:
    rows: dict[str, TechnicalProfile] = field(default_factory=dict)

    def get(self, profile_id: str) -> TechnicalProfile | None:
        return self.rows.get(profile_id)


@dataclass
class SpySender:
    messages: list[str] = field(default_factory=list)

    def send(self, message: str) -> None:
        self.messages.append(message)


def _watch_item(ticker: str) -> WatchlistItem:
    return WatchlistItem(
        ticker=ticker,
        name="富士フイルム",
        metric_type=MetricType.PER,
        notify_channel=NotifyChannel.DISCORD,
        notify_timing=NotifyTiming.IMMEDIATE,
        technical_profile_id="custom_profile",
    )


def _indicator(trade_date: str, **values) -> TechnicalIndicatorsDaily:
    return TechnicalIndicatorsDaily(
        ticker="3901:TSE",
        trade_date=trade_date,
        schema_version=1,
        calculated_at=f"{trade_date}T06:00:00+00:00",
        values=values,
    )


class TechnicalPipelineTest(unittest.TestCase):
    def test_pipeline_sends_cross_alert_and_updates_state(self) -> None:
        indicators_repo = InMemoryTechnicalIndicatorsRepo(
            rows=[
                _indicator("2026-03-08", close_vs_ma25=0.5),
                _indicator("2026-03-07", close_vs_ma25=-0.4),
            ]
        )
        rules_repo = InMemoryTechnicalAlertRulesRepo(
            rows=[
                TechnicalAlertRule.create(
                    ticker="3901:TSE",
                    rule_name="25日線回復",
                    field_key="close_vs_ma25",
                    operator=TechnicalAlertOperator.GTE,
                    threshold_value=0.0,
                    note="終値ベース",
                    rule_id="rule-ma25",
                )
            ]
        )
        state_repo = InMemoryTechnicalAlertStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_technical_alert_pipeline(
            watchlist_items=[_watch_item("3901:TSE")],
            technical_indicators_repo=indicators_repo,
            technical_alert_rules_repo=rules_repo,
            technical_alert_state_repo=state_repo,
            notification_log_repo=log_repo,
            technical_profiles_repo=InMemoryTechnicalProfilesRepo(),
            sender=sender,
            config=TechnicalAlertPipelineConfig(
                trade_date="2026-03-08",
                cooldown_hours=2,
                now_iso="2026-03-08T06:30:00+00:00",
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(result.skipped_notifications, 0)
        self.assertEqual(len(sender.messages), 1)
        self.assertIn("【技術アラート】3901:TSE 富士フイルム", sender.messages[0])
        self.assertIn("ルール名: 25日線回復", sender.messages[0])
        self.assertIn("現在値: 0.50", sender.messages[0])
        self.assertIn("しきい値: >= 0.00", sender.messages[0])
        self.assertEqual(log_repo.rows[0].condition_key, "TECH:rule-ma25")
        state = state_repo.get("3901:TSE", "rule-ma25")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertTrue(state.last_condition_met)
        self.assertEqual(state.last_triggered_at, "2026-03-08T06:30:00+00:00")

    def test_pipeline_uses_cooldown_and_still_updates_state(self) -> None:
        indicators_repo = InMemoryTechnicalIndicatorsRepo(
            rows=[
                _indicator("2026-03-08", cross_up_ma25=True),
                _indicator("2026-03-07", cross_up_ma25=False),
            ]
        )
        rules_repo = InMemoryTechnicalAlertRulesRepo(
            rows=[
                TechnicalAlertRule.create(
                    ticker="3901:TSE",
                    rule_name="25日線上抜け",
                    field_key="cross_up_ma25",
                    operator=TechnicalAlertOperator.IS_TRUE,
                    rule_id="rule-cross",
                )
            ]
        )
        state_repo = InMemoryTechnicalAlertStateRepo()
        log_repo = InMemoryNotificationLogRepo(
            rows=[
                NotificationLogEntry(
                    entry_id="log-1",
                    ticker="3901:TSE",
                    category="技術アラート",
                    condition_key="TECH:rule-cross",
                    sent_at="2026-03-08T05:30:00+00:00",
                    channel="DISCORD",
                    payload_hash="hash",
                    is_strong=False,
                    body="old",
                )
            ]
        )
        sender = SpySender()

        result = run_technical_alert_pipeline(
            watchlist_items=[_watch_item("3901:TSE")],
            technical_indicators_repo=indicators_repo,
            technical_alert_rules_repo=rules_repo,
            technical_alert_state_repo=state_repo,
            notification_log_repo=log_repo,
            technical_profiles_repo=InMemoryTechnicalProfilesRepo(),
            sender=sender,
            config=TechnicalAlertPipelineConfig(
                trade_date="2026-03-08",
                cooldown_hours=2,
                now_iso="2026-03-08T06:30:00+00:00",
            ),
        )

        self.assertEqual(result.sent_notifications, 0)
        self.assertEqual(result.skipped_notifications, 1)
        self.assertEqual(sender.messages, [])
        state = state_repo.get("3901:TSE", "rule-cross")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertTrue(state.last_condition_met)
        self.assertIsNone(state.last_triggered_at)

    def test_pipeline_skips_stale_indicator_trade_date(self) -> None:
        indicators_repo = InMemoryTechnicalIndicatorsRepo(
            rows=[_indicator("2026-03-07", cross_up_ma25=True)]
        )
        rules_repo = InMemoryTechnicalAlertRulesRepo(
            rows=[
                TechnicalAlertRule.create(
                    ticker="3901:TSE",
                    rule_name="25日線上抜け",
                    field_key="cross_up_ma25",
                    operator=TechnicalAlertOperator.IS_TRUE,
                    rule_id="rule-stale",
                )
            ]
        )
        state_repo = InMemoryTechnicalAlertStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()

        result = run_technical_alert_pipeline(
            watchlist_items=[_watch_item("3901:TSE")],
            technical_indicators_repo=indicators_repo,
            technical_alert_rules_repo=rules_repo,
            technical_alert_state_repo=state_repo,
            notification_log_repo=log_repo,
            technical_profiles_repo=InMemoryTechnicalProfilesRepo(),
            sender=sender,
            config=TechnicalAlertPipelineConfig(
                trade_date="2026-03-08",
                cooldown_hours=2,
                now_iso="2026-03-08T06:30:00+00:00",
                execution_mode=NotificationExecutionMode.ALL,
            ),
        )

        self.assertEqual(result.processed_tickers, 1)
        self.assertEqual(result.sent_notifications, 0)
        self.assertEqual(state_repo.rows, [])
        self.assertEqual(sender.messages, [])

    def test_pipeline_marks_profile_strong_alert_and_can_suppress_weak_alert(self) -> None:
        indicators_repo = InMemoryTechnicalIndicatorsRepo(
            rows=[
                _indicator("2026-03-08", cross_down_ma200=True, turnover_spike=True),
                _indicator("2026-03-07", cross_down_ma200=False, turnover_spike=False),
            ]
        )
        rules_repo = InMemoryTechnicalAlertRulesRepo(
            rows=[
                TechnicalAlertRule.create(
                    ticker="3901:TSE",
                    rule_name="200日線下抜け",
                    field_key="cross_down_ma200",
                    operator=TechnicalAlertOperator.IS_TRUE,
                    rule_id="rule-strong",
                ),
                TechnicalAlertRule.create(
                    ticker="3901:TSE",
                    rule_name="売買代金スパイク",
                    field_key="turnover_spike",
                    operator=TechnicalAlertOperator.IS_TRUE,
                    rule_id="rule-weak",
                ),
            ]
        )
        state_repo = InMemoryTechnicalAlertStateRepo()
        log_repo = InMemoryNotificationLogRepo()
        sender = SpySender()
        profiles_repo = InMemoryTechnicalProfilesRepo(
            rows={
                "custom_profile": TechnicalProfile(
                    profile_id="custom_profile",
                    profile_type=TechnicalProfileType.CUSTOM,
                    profile_key="custom_profile",
                    name="カスタム",
                    description="テスト",
                    flags={"suppress_minor_alerts": True},
                    strong_alerts=("cross_down_ma200",),
                    weak_alerts=("turnover_spike",),
                )
            }
        )

        result = run_technical_alert_pipeline(
            watchlist_items=[_watch_item("3901:TSE")],
            technical_indicators_repo=indicators_repo,
            technical_alert_rules_repo=rules_repo,
            technical_alert_state_repo=state_repo,
            notification_log_repo=log_repo,
            technical_profiles_repo=profiles_repo,
            sender=sender,
            config=TechnicalAlertPipelineConfig(
                trade_date="2026-03-08",
                cooldown_hours=2,
                now_iso="2026-03-08T06:30:00+00:00",
            ),
        )

        self.assertEqual(result.sent_notifications, 1)
        self.assertEqual(len(log_repo.rows), 1)
        self.assertTrue(log_repo.rows[0].is_strong)
        self.assertEqual(log_repo.rows[0].condition_key, "TECH:rule-strong")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import uvicorn

from kabu_per_bot.admin_ops import AdminOpsJob, AdminOpsSummary, BackfillRunRequest, JobExecution, TickerScopedRunRequest
from kabu_per_bot.api.app import create_app
from kabu_per_bot.api.errors import UnauthorizedError
from kabu_per_bot.grok_sns_settings import GrokSnsSettings
from kabu_per_bot.immediate_schedule import ImmediateSchedule
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings
from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.storage.firestore_schema import normalize_ticker
from kabu_per_bot.technical import TechnicalAlertOperator, TechnicalAlertRule, TechnicalIndicatorsDaily
from kabu_per_bot.watchlist import (
    CreateResult,
    MetricType,
    NotifyChannel,
    NotifyTiming,
    WatchlistHistoryAction,
    WatchlistHistoryRecord,
    WatchlistItem,
    WatchlistService,
)


@dataclass
class InMemoryWatchlistRepository:
    docs: dict[str, WatchlistItem] = field(default_factory=dict)

    def try_create(self, item: WatchlistItem, *, max_items: int) -> CreateResult:
        if item.ticker in self.docs:
            return CreateResult.DUPLICATE
        if len(self.docs) >= max_items:
            return CreateResult.LIMIT_EXCEEDED
        self.docs[item.ticker] = item
        return CreateResult.CREATED

    def count(self) -> int:
        return len(self.docs)

    def get(self, ticker: str) -> WatchlistItem | None:
        return self.docs.get(normalize_ticker(ticker))

    def list_all(self) -> list[WatchlistItem]:
        return sorted(self.docs.values(), key=lambda item: item.ticker)

    def create(self, item: WatchlistItem) -> None:
        self.docs[item.ticker] = item

    def update(self, item: WatchlistItem) -> None:
        self.docs[item.ticker] = item

    def delete(self, ticker: str) -> bool:
        normalized = normalize_ticker(ticker)
        if normalized not in self.docs:
            return False
        del self.docs[normalized]
        return True


@dataclass
class InMemoryWatchlistHistoryRepository:
    rows: list[WatchlistHistoryRecord] = field(default_factory=list)

    def append(self, record: WatchlistHistoryRecord) -> None:
        self.rows.append(record)

    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[WatchlistHistoryRecord]:
        values = list(self.rows)
        if ticker:
            normalized = normalize_ticker(ticker)
            values = [row for row in values if row.ticker == normalized]
        values.sort(key=lambda row: row.acted_at, reverse=True)
        if limit is None:
            return values[offset:]
        return values[offset : offset + limit]

    def count_timeline(self, *, ticker: str | None = None) -> int:
        if ticker is None:
            return len(self.rows)
        normalized = normalize_ticker(ticker)
        return sum(1 for row in self.rows if row.ticker == normalized)


@dataclass
class InMemoryNotificationLogRepository:
    rows: list[NotificationLogEntry] = field(default_factory=list)
    failed_job_value: bool = False

    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        category: str | None = None,
        is_strong: bool | None = None,
        limit: int | None = 100,
        offset: int = 0,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> list[NotificationLogEntry]:
        values = list(self.rows)
        if ticker:
            normalized = normalize_ticker(ticker)
            values = [row for row in values if row.ticker == normalized]
        if category:
            normalized_category = category.strip()
            values = [row for row in values if row.category == normalized_category]
        if is_strong is not None:
            values = [row for row in values if row.is_strong is is_strong]
        if sent_at_from:
            from_dt = _parse_iso_datetime(sent_at_from)
            values = [row for row in values if _parse_iso_datetime(row.sent_at) >= from_dt]
        if sent_at_to:
            to_dt = _parse_iso_datetime(sent_at_to)
            values = [row for row in values if _parse_iso_datetime(row.sent_at) < to_dt]
        values.sort(key=lambda row: _parse_iso_datetime(row.sent_at), reverse=True)
        if limit is None:
            return values[offset:]
        return values[offset : offset + limit]

    def count_timeline(
        self,
        *,
        ticker: str | None = None,
        category: str | None = None,
        is_strong: bool | None = None,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> int:
        return len(
            self.list_timeline(
                ticker=ticker,
                category=category,
                is_strong=is_strong,
                sent_at_from=sent_at_from,
                sent_at_to=sent_at_to,
                limit=None,
                offset=0,
            )
        )

    def failed_job_exists(
        self,
        *,
        sent_at_from: str,
        sent_at_to: str,
    ) -> bool:
        return self.failed_job_value


@dataclass
class InMemoryGlobalSettingsRepository:
    settings: GlobalRuntimeSettings = field(
        default_factory=lambda: GlobalRuntimeSettings(
            cooldown_hours=2,
            intel_notification_max_age_days=30,
            immediate_schedule=ImmediateSchedule.default(),
            grok_sns_settings=GrokSnsSettings.default(),
            committee_daily_scheduled_time="18:00",
            baseline_monthly_scheduled_time="18:00",
            updated_at=None,
            updated_by=None,
        )
    )

    def get_global_settings(self) -> GlobalRuntimeSettings:
        return self.settings

    def upsert_global_settings(
        self,
        *,
        cooldown_hours: int | None = None,
        intel_notification_max_age_days: int | None = None,
        immediate_schedule: ImmediateSchedule | None = None,
        grok_sns_settings: GrokSnsSettings | None = None,
        committee_daily_scheduled_time: str | None = None,
        baseline_monthly_scheduled_time: str | None = None,
        updated_at: str,
        updated_by: str | None,
    ) -> None:
        self.settings = GlobalRuntimeSettings(
            cooldown_hours=(self.settings.cooldown_hours if cooldown_hours is None else cooldown_hours),
            intel_notification_max_age_days=(
                self.settings.intel_notification_max_age_days
                if intel_notification_max_age_days is None
                else intel_notification_max_age_days
            ),
            immediate_schedule=(self.settings.immediate_schedule if immediate_schedule is None else immediate_schedule),
            grok_sns_settings=(self.settings.grok_sns_settings if grok_sns_settings is None else grok_sns_settings),
            committee_daily_scheduled_time=(
                self.settings.committee_daily_scheduled_time
                if committee_daily_scheduled_time is None
                else committee_daily_scheduled_time
            ),
            baseline_monthly_scheduled_time=(
                self.settings.baseline_monthly_scheduled_time
                if baseline_monthly_scheduled_time is None
                else baseline_monthly_scheduled_time
            ),
            updated_at=updated_at,
            updated_by=updated_by,
        )


@dataclass
class InMemoryAdminOpsService:
    executions: list[JobExecution] = field(default_factory=list)

    def list_jobs(self) -> tuple[AdminOpsJob, ...]:
        return (
            AdminOpsJob(key="immediate_open", label="寄り付き帯ジョブ（IMMEDIATE）", job_name="kabu-immediate-open"),
            AdminOpsJob(key="immediate_close", label="引け帯ジョブ（IMMEDIATE）", job_name="kabu-immediate-close"),
            AdminOpsJob(key="daily", label="日次ジョブ（IMMEDIATE）", job_name="kabu-daily"),
            AdminOpsJob(key="daily_at21", label="21:05ジョブ（AT_21）", job_name="kabu-daily-at21"),
            AdminOpsJob(key="earnings_weekly", label="今週決算ジョブ", job_name="kabu-earnings-weekly"),
            AdminOpsJob(key="earnings_tomorrow", label="明日決算ジョブ", job_name="kabu-earnings-tomorrow"),
            AdminOpsJob(key="committee_baseline_refresh", label="基礎調査月次更新ジョブ", job_name="kabu-baseline-research"),
            AdminOpsJob(key="backfill", label="バックフィルジョブ", job_name="kabu-backfill"),
            AdminOpsJob(key="technical_daily", label="技術日次ジョブ", job_name="kabu-technical-daily"),
            AdminOpsJob(key="technical_full_refresh", label="技術全件再同期ジョブ", job_name="kabu-technical-full-refresh"),
            AdminOpsJob(
                key="technical_profile_auto_assign",
                label="技術プロファイル自動割当ジョブ",
                job_name="kabu-technical-profile-auto-assign",
            ),
        )

    def list_executions(self, *, job_key: str, limit: int = 20) -> tuple[JobExecution, ...]:
        values = [row for row in self.executions if row.job_key == job_key]
        return tuple(values[:limit])

    def run_job(
        self,
        *,
        job_key: str,
        backfill: BackfillRunRequest | None = None,
        ticker_scope: TickerScopedRunRequest | None = None,
    ) -> JobExecution:
        _ = backfill, ticker_scope
        now_iso = datetime.now(timezone.utc).isoformat()
        job = next((row for row in self.list_jobs() if row.key == job_key), None)
        if job is None or not job.job_name:
            raise ValueError(f"unsupported job_key: {job_key}")
        execution = JobExecution(
            job_key=job.key,
            job_label=job.label,
            job_name=job.job_name,
            execution_name=f"{job.job_name}-e2e-{len(self.executions) + 1}",
            status="SUCCEEDED",
            create_time=now_iso,
            start_time=now_iso,
            completion_time=now_iso,
            message="e2e execution completed",
            log_uri=None,
            skip_reasons=(),
            skip_reason_error=None,
        )
        self.executions.insert(0, execution)
        return execution

    def get_summary(
        self,
        *,
        limit_per_job: int = 5,
        include_recent_executions: bool = True,
        include_skip_reasons: bool = True,
    ) -> AdminOpsSummary:
        _ = limit_per_job
        return AdminOpsSummary(
            jobs=self.list_jobs(),
            recent_executions=tuple(self.executions[:20]) if include_recent_executions else tuple(),
            latest_skip_reasons=tuple(self.executions[:5]) if include_skip_reasons else tuple(),
        )

    def send_discord_test(self, *, requested_uid: str) -> str:
        _ = requested_uid
        return datetime.now(timezone.utc).isoformat()


@dataclass
class InMemoryTechnicalAlertRulesRepository:
    rows: list[TechnicalAlertRule] = field(default_factory=list)

    def get(self, ticker: str, rule_id: str) -> TechnicalAlertRule | None:
        normalized_ticker = normalize_ticker(ticker)
        for row in self.rows:
            if row.ticker == normalized_ticker and row.rule_id == rule_id:
                return row
        return None

    def upsert(self, rule: TechnicalAlertRule) -> None:
        current = self.get(rule.ticker, rule.rule_id)
        if current is None:
            self.rows.append(rule)
            return
        index = self.rows.index(current)
        self.rows[index] = rule

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalAlertRule]:
        normalized_ticker = normalize_ticker(ticker)
        rows = [row for row in self.rows if row.ticker == normalized_ticker]
        rows.sort(key=lambda row: row.updated_at or row.created_at or "", reverse=True)
        return rows[:limit]


@dataclass
class InMemoryTechnicalIndicatorsRepository:
    rows: list[TechnicalIndicatorsDaily] = field(default_factory=list)

    def get(self, ticker: str, trade_date: str) -> TechnicalIndicatorsDaily | None:
        normalized_ticker = normalize_ticker(ticker)
        for row in self.rows:
            if row.ticker == normalized_ticker and row.trade_date == trade_date:
                return row
        return None

    def upsert(self, indicators: TechnicalIndicatorsDaily) -> None:
        current = self.get(indicators.ticker, indicators.trade_date)
        if current is None:
            self.rows.append(indicators)
            return
        index = self.rows.index(current)
        self.rows[index] = indicators

    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalIndicatorsDaily]:
        normalized_ticker = normalize_ticker(ticker)
        rows = [row for row in self.rows if row.ticker == normalized_ticker]
        rows.sort(key=lambda row: row.trade_date, reverse=True)
        return rows[:limit]


class WebE2ETokenVerifier:
    def verify(self, token: str) -> dict[str, object]:
        if token in {"mock-token", "valid-token"}:
            return {"uid": "web-e2e-user", "admin": True}
        raise UnauthorizedError("認証に失敗しました。")


def _watchlist_item(
    *,
    ticker: str,
    name: str,
    metric_type: MetricType,
    notify_channel: NotifyChannel,
    notify_timing: NotifyTiming,
    is_active: bool,
    ai_enabled: bool,
) -> WatchlistItem:
    now_iso = datetime.now(timezone.utc).isoformat()
    return WatchlistItem(
        ticker=normalize_ticker(ticker),
        name=name,
        metric_type=metric_type,
        notify_channel=notify_channel,
        notify_timing=notify_timing,
        is_active=is_active,
        ai_enabled=ai_enabled,
        created_at=now_iso,
        updated_at=now_iso,
    )


def _seed_watchlist_items() -> list[WatchlistItem]:
    return [
        _watchlist_item(
            ticker="1332:TSE",
            name="ニッスイ",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            is_active=True,
            ai_enabled=False,
        ),
        _watchlist_item(
            ticker="1605:TSE",
            name="INPEX",
            metric_type=MetricType.PSR,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.AT_21,
            is_active=True,
            ai_enabled=True,
        ),
        _watchlist_item(
            ticker="2914:TSE",
            name="JT",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.OFF,
            is_active=False,
            ai_enabled=False,
        ),
        _watchlist_item(
            ticker="4063:TSE",
            name="信越化学工業",
            metric_type=MetricType.PSR,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            is_active=True,
            ai_enabled=True,
        ),
        _watchlist_item(
            ticker="4502:TSE",
            name="武田薬品工業",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.OFF,
            notify_timing=NotifyTiming.OFF,
            is_active=True,
            ai_enabled=False,
        ),
        _watchlist_item(
            ticker="6367:TSE",
            name="ダイキン工業",
            metric_type=MetricType.PSR,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.AT_21,
            is_active=True,
            ai_enabled=False,
        ),
        _watchlist_item(
            ticker="6501:TSE",
            name="日立製作所",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            is_active=True,
            ai_enabled=True,
        ),
        _watchlist_item(
            ticker="6758:TSE",
            name="ソニーグループ",
            metric_type=MetricType.PSR,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.AT_21,
            is_active=True,
            ai_enabled=False,
        ),
        _watchlist_item(
            ticker="7203:TSE",
            name="トヨタ自動車",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.IMMEDIATE,
            is_active=True,
            ai_enabled=False,
        ),
        _watchlist_item(
            ticker="8035:TSE",
            name="東京エレクトロン",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.AT_21,
            is_active=True,
            ai_enabled=True,
        ),
        _watchlist_item(
            ticker="8058:TSE",
            name="三菱商事",
            metric_type=MetricType.PSR,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.OFF,
            is_active=False,
            ai_enabled=False,
        ),
        _watchlist_item(
            ticker="9432:TSE",
            name="日本電信電話",
            metric_type=MetricType.PER,
            notify_channel=NotifyChannel.DISCORD,
            notify_timing=NotifyTiming.AT_21,
            is_active=True,
            ai_enabled=False,
        ),
    ]


def _seed_watchlist_history() -> list[WatchlistHistoryRecord]:
    return [
        WatchlistHistoryRecord.create(
            ticker="7203:TSE",
            action=WatchlistHistoryAction.REMOVE,
            reason="監視対象見直し",
            acted_at="2026-02-11T13:20:05+09:00",
        ),
        WatchlistHistoryRecord.create(
            ticker="7203:TSE",
            action=WatchlistHistoryAction.ADD,
            reason="PER監視追加",
            acted_at="2026-02-10T09:35:42+09:00",
        ),
        WatchlistHistoryRecord.create(
            ticker="9432:TSE",
            action=WatchlistHistoryAction.REMOVE,
            reason="通知停止",
            acted_at="2026-02-09T21:10:15+09:00",
        ),
        WatchlistHistoryRecord.create(
            ticker="9432:TSE",
            action=WatchlistHistoryAction.ADD,
            reason="監視再開",
            acted_at="2026-02-08T10:01:11+09:00",
        ),
        WatchlistHistoryRecord.create(
            ticker="6501:TSE",
            action=WatchlistHistoryAction.ADD,
            reason="初回登録",
            acted_at="2026-02-07T08:45:00+09:00",
        ),
    ]


def _seed_notification_logs() -> list[NotificationLogEntry]:
    return [
        NotificationLogEntry(
            entry_id="log-20260212-01",
            ticker="7203:TSE",
            category="PER",
            condition_key="PER:1W:UNDER",
            sent_at="2026-02-12T08:10:00+09:00",
            channel="DISCORD",
            payload_hash="af1b9c2d",
            is_strong=False,
        ),
        NotificationLogEntry(
            entry_id="log-20260211-02",
            ticker="6501:TSE",
            category="PSR",
            condition_key="PSR:3M:UNDER_STRONG",
            sent_at="2026-02-11T21:00:00+09:00",
            channel="DISCORD",
            payload_hash="8d1efaa0",
            is_strong=True,
        ),
        NotificationLogEntry(
            entry_id="log-20260211-tech-01",
            ticker="6501:TSE",
            category="技術アラート",
            condition_key="TECHNICAL:volume_ratio:GTE",
            sent_at="2026-02-11T14:40:00+09:00",
            channel="DISCORD",
            payload_hash="tech8d1efaa0",
            is_strong=False,
            body="出来高倍率が2.00以上になりました。",
        ),
        NotificationLogEntry(
            entry_id="log-20260211-01",
            ticker="9432:TSE",
            category="データ不明",
            condition_key="DATA_UNKNOWN",
            sent_at="2026-02-11T07:45:10+09:00",
            channel="DISCORD",
            payload_hash="90cde110",
            is_strong=False,
        ),
        NotificationLogEntry(
            entry_id="log-20260210-01",
            ticker="8035:TSE",
            category="決算",
            condition_key="EARNINGS:BEFORE_OPEN",
            sent_at="2026-02-10T06:30:00+09:00",
            channel="DISCORD",
            payload_hash="b0f1974e",
            is_strong=False,
        ),
    ]


def _seed_technical_alert_rules() -> list[TechnicalAlertRule]:
    return [
        TechnicalAlertRule.create(
            ticker="6501:TSE",
            rule_id="rule-volume-ratio",
            rule_name="出来高急増",
            field_key="volume_ratio",
            operator=TechnicalAlertOperator.GTE,
            threshold_value=2.0,
            is_active=True,
            note="20日中央値比で急増を監視",
            created_at="2026-02-10T09:00:00+09:00",
            updated_at="2026-02-11T14:35:00+09:00",
        )
    ]


def _seed_technical_indicators() -> list[TechnicalIndicatorsDaily]:
    return [
        TechnicalIndicatorsDaily(
            ticker="6501:TSE",
            trade_date="2026-02-11",
            schema_version=1,
            calculated_at="2026-02-11T15:31:00+09:00",
            values={
                "close_vs_ma25": 4.21,
                "close_vs_ma75": 8.45,
                "close_vs_ma200": 18.22,
                "volume_ratio": 2.31,
                "turnover_ratio": 1.84,
                "atr_pct_14": 2.18,
                "volatility_20d": 24.7,
                "cross_up_ma25": True,
                "new_high_20d": True,
            },
        )
    ]


def create_web_e2e_app() -> Any:
    watchlist_repo = InMemoryWatchlistRepository()
    for item in _seed_watchlist_items():
        watchlist_repo.create(item)

    history_repo = InMemoryWatchlistHistoryRepository(_seed_watchlist_history())
    notification_repo = InMemoryNotificationLogRepository(_seed_notification_logs(), failed_job_value=False)
    admin_ops_service = InMemoryAdminOpsService()
    global_settings_repo = InMemoryGlobalSettingsRepository()
    technical_rules_repo = InMemoryTechnicalAlertRulesRepository(_seed_technical_alert_rules())
    technical_indicators_repo = InMemoryTechnicalIndicatorsRepository(_seed_technical_indicators())
    watchlist_service = WatchlistService(
        watchlist_repo,
        max_items=100,
        history_repository=history_repo,
    )
    return create_app(
        watchlist_service=watchlist_service,
        watchlist_history_repository=history_repo,
        notification_log_repository=notification_repo,
        admin_ops_service=admin_ops_service,
        global_settings_repository=global_settings_repo,
        technical_alert_rules_repository=technical_rules_repo,
        technical_indicators_repository=technical_indicators_repo,
        token_verifier=WebE2ETokenVerifier(),
    )


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local FastAPI test server for Web API-integration E2E.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    app = create_web_e2e_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

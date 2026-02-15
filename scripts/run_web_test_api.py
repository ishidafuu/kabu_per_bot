from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import uvicorn

from kabu_per_bot.api.app import create_app
from kabu_per_bot.api.errors import UnauthorizedError
from kabu_per_bot.signal import NotificationLogEntry
from kabu_per_bot.storage.firestore_schema import normalize_ticker
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
    failed_job_value: bool | None = False

    def list_timeline(
        self,
        *,
        ticker: str | None = None,
        limit: int | None = 100,
        offset: int = 0,
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> list[NotificationLogEntry]:
        values = list(self.rows)
        if ticker:
            normalized = normalize_ticker(ticker)
            values = [row for row in values if row.ticker == normalized]
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
        sent_at_from: str | None = None,
        sent_at_to: str | None = None,
    ) -> int:
        return len(
            self.list_timeline(
                ticker=ticker,
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
    ) -> bool | None:
        return self.failed_job_value


class WebE2ETokenVerifier:
    def verify(self, token: str) -> dict[str, str]:
        if token in {"mock-token", "valid-token"}:
            return {"uid": "web-e2e-user"}
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


def create_web_e2e_app() -> Any:
    watchlist_repo = InMemoryWatchlistRepository()
    for item in _seed_watchlist_items():
        watchlist_repo.create(item)

    history_repo = InMemoryWatchlistHistoryRepository(_seed_watchlist_history())
    notification_repo = InMemoryNotificationLogRepository(_seed_notification_logs(), failed_job_value=False)
    watchlist_service = WatchlistService(
        watchlist_repo,
        max_items=100,
        history_repository=history_repo,
    )
    return create_app(
        watchlist_service=watchlist_service,
        watchlist_history_repository=history_repo,
        notification_log_repository=notification_repo,
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

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha1
import logging
from statistics import mean
from typing import Protocol

from kabu_per_bot.market_data import MarketDataError, MarketDataSource
from kabu_per_bot.metrics import DailyMetric
from kabu_per_bot.pipeline import NotificationExecutionMode
from kabu_per_bot.signal import NotificationLogEntry, evaluate_cooldown
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date
from kabu_per_bot.watchlist import NotifyChannel, NotifyTiming, WatchPriority, WatchlistItem


LOGGER = logging.getLogger(__name__)
_PHASE_A_CATEGORY = "フェイズA保有"


class MessageSender(Protocol):
    def send(self, message: str) -> None:
        """Send outbound message."""


class DailyMetricsRepository(Protocol):
    def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
        """Get recent metric rows."""


class NotificationLogRepository(Protocol):
    def append(self, entry: NotificationLogEntry) -> None:
        """Persist notification log."""

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        """Get recent notification log rows."""


@dataclass(frozen=True)
class PhaseAHoldingsConfig:
    trade_date: str
    now_iso: str
    cooldown_hours: int
    channel: str = "DISCORD_DAILY"
    execution_mode: NotificationExecutionMode = NotificationExecutionMode.DAILY
    max_focus_items: int = 3
    daily_change_threshold_pct: float = 4.0
    weekly_change_threshold_pct: float = 8.0
    earnings_gate_e3_days: int = 5
    earnings_gate_e2_days: int = 10
    earnings_gate_e1_days: int = 15
    trend_ma_short_days: int = 20
    trend_ma_long_days: int = 60


@dataclass(frozen=True)
class PhaseAHoldingBrief:
    ticker: str
    company_name: str
    watch_priority: WatchPriority
    role_label: str
    latest_close: float | None
    day_change_pct: float | None
    week_change_pct: float | None
    ma_short: float | None
    ma_long: float | None
    trend_label: str
    earnings_days: int | None
    earnings_gate_code: str
    earnings_gate_rank: int
    risk_points: int
    risk_level: str
    risk_rank: int
    risk_reasons: tuple[str, ...]
    action_candidates: tuple[str, ...]
    data_source: str | None
    data_fetched_at: str | None


@dataclass(frozen=True)
class PhaseAResult:
    processed_tickers: int = 0
    sent_notifications: int = 0
    skipped_notifications: int = 0
    errors: int = 0

    def merge(self, other: "PhaseAResult") -> "PhaseAResult":
        return PhaseAResult(
            processed_tickers=self.processed_tickers + other.processed_tickers,
            sent_notifications=self.sent_notifications + other.sent_notifications,
            skipped_notifications=self.skipped_notifications + other.skipped_notifications,
            errors=self.errors + other.errors,
        )


def run_holdings_phase_a_pipeline(
    *,
    watchlist_items: list[WatchlistItem],
    market_data_source: MarketDataSource,
    daily_metrics_repo: DailyMetricsRepository,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    config: PhaseAHoldingsConfig,
) -> PhaseAResult:
    trade_date = normalize_trade_date(config.trade_date)
    briefs: list[PhaseAHoldingBrief] = []
    result = PhaseAResult()

    for item in watchlist_items:
        if not item.is_active:
            continue
        if not _is_channel_enabled(item=item, channel=config.channel):
            continue
        if not _should_dispatch_for_timing(item.notify_timing, config.execution_mode):
            continue

        try:
            brief = _build_brief(
                item=item,
                trade_date=trade_date,
                market_data_source=market_data_source,
                daily_metrics_repo=daily_metrics_repo,
                config=config,
            )
            briefs.append(brief)
            result = result.merge(PhaseAResult(processed_tickers=1))
        except Exception as exc:
            LOGGER.exception("フェイズA判定失敗: ticker=%s error=%s", item.ticker, exc)
            result = result.merge(PhaseAResult(processed_tickers=1, errors=1))

    focus_briefs = _select_focus_briefs(briefs=briefs, max_items=config.max_focus_items)
    for brief in focus_briefs:
        body = _format_phase_a_message(brief=brief, trade_date=trade_date, config=config)
        sent, skipped = _dispatch_with_cooldown(
            ticker=brief.ticker,
            body=body,
            condition_key=f"PHASE_A:{trade_date}:{brief.risk_level}:{brief.earnings_gate_code}",
            is_strong=brief.risk_rank >= 2,
            now_iso=config.now_iso,
            cooldown_hours=config.cooldown_hours,
            channel=config.channel,
            data_source=brief.data_source,
            data_fetched_at=brief.data_fetched_at,
            notification_log_repo=notification_log_repo,
            sender=sender,
        )
        result = result.merge(PhaseAResult(sent_notifications=sent, skipped_notifications=skipped))
    return result


def _build_brief(
    *,
    item: WatchlistItem,
    trade_date: str,
    market_data_source: MarketDataSource,
    daily_metrics_repo: DailyMetricsRepository,
    config: PhaseAHoldingsConfig,
) -> PhaseAHoldingBrief:
    role_label = _role_label(item.priority)
    recent_metrics = daily_metrics_repo.list_recent(item.ticker, limit=max(config.trend_ma_long_days + 2, 70))
    close_history = [row.close_price for row in recent_metrics if row.close_price is not None and row.close_price > 0]
    latest_close = close_history[0] if close_history else None
    day_change_pct = _change_pct(current=latest_close, previous=close_history[1] if len(close_history) >= 2 else None)
    week_change_pct = _change_pct(current=latest_close, previous=close_history[5] if len(close_history) >= 6 else None)
    ma_short = _rolling_mean(values=close_history, window=config.trend_ma_short_days)
    ma_long = _rolling_mean(values=close_history, window=config.trend_ma_long_days)
    trend_is_bearish = latest_close is not None and ma_long is not None and latest_close < ma_long
    trend_label = "下振れ" if trend_is_bearish else ("維持" if ma_long is not None else "判定不能")

    earnings_days: int | None = None
    data_source: str | None = None
    data_fetched_at: str | None = None
    try:
        snapshot = market_data_source.fetch_snapshot(item.ticker)
        earnings_days = _resolve_earnings_days(trade_date=trade_date, earnings_date=snapshot.earnings_date)
        data_source = snapshot.source
        data_fetched_at = snapshot.fetched_at
    except MarketDataError as exc:
        LOGGER.warning("フェイズAの決算日取得失敗: ticker=%s error=%s", item.ticker, exc)

    earnings_gate_code, earnings_gate_rank = _earnings_gate(earnings_days=earnings_days, config=config)
    risk_points = 0
    risk_reasons: list[str] = []

    if earnings_days is None:
        risk_points += 1
        risk_reasons.append("決算日が不明")
    elif earnings_days <= config.earnings_gate_e2_days:
        risk_points += 1
        risk_reasons.append(f"決算まで{earnings_days}日")

    if day_change_pct is None:
        risk_points += 1
        risk_reasons.append("日次騰落率を算出不可")
    elif abs(day_change_pct) >= config.daily_change_threshold_pct:
        risk_points += 1
        risk_reasons.append(f"日次騰落率 {day_change_pct:+.1f}%")

    if week_change_pct is None:
        risk_points += 1
        risk_reasons.append("週次騰落率を算出不可")
    elif abs(week_change_pct) >= config.weekly_change_threshold_pct:
        risk_points += 1
        risk_reasons.append(f"週次騰落率 {week_change_pct:+.1f}%")

    if trend_is_bearish:
        risk_points += 1
        risk_reasons.append(f"終値がMA{config.trend_ma_long_days}を下回り")

    risk_level, risk_rank = _risk_level(risk_points=risk_points)
    actions = _action_candidates(
        risk_rank=risk_rank,
        earnings_gate_rank=earnings_gate_rank,
    )

    return PhaseAHoldingBrief(
        ticker=normalize_ticker(item.ticker),
        company_name=item.name,
        watch_priority=item.priority,
        role_label=role_label,
        latest_close=latest_close,
        day_change_pct=day_change_pct,
        week_change_pct=week_change_pct,
        ma_short=ma_short,
        ma_long=ma_long,
        trend_label=trend_label,
        earnings_days=earnings_days,
        earnings_gate_code=earnings_gate_code,
        earnings_gate_rank=earnings_gate_rank,
        risk_points=risk_points,
        risk_level=risk_level,
        risk_rank=risk_rank,
        risk_reasons=tuple(risk_reasons) if risk_reasons else ("目立つリスクなし",),
        action_candidates=tuple(actions),
        data_source=data_source,
        data_fetched_at=data_fetched_at,
    )


def _select_focus_briefs(*, briefs: list[PhaseAHoldingBrief], max_items: int) -> list[PhaseAHoldingBrief]:
    if max_items <= 0:
        return []

    focus: list[PhaseAHoldingBrief] = []
    for brief in briefs:
        if brief.watch_priority is WatchPriority.HIGH:
            focus.append(brief)
            continue
        if brief.watch_priority is WatchPriority.MEDIUM and (brief.risk_rank >= 2 or brief.earnings_gate_rank >= 2):
            focus.append(brief)
            continue
        if brief.watch_priority is WatchPriority.LOW and (brief.risk_rank >= 3 or brief.earnings_gate_rank >= 3):
            focus.append(brief)

    if not focus:
        fallback = sorted(briefs, key=_brief_sort_key)
        return fallback[:1]

    focus.sort(key=_brief_sort_key)
    return focus[:max_items]


def _brief_sort_key(brief: PhaseAHoldingBrief) -> tuple[int, int, int, str]:
    priority_rank = {
        WatchPriority.HIGH: 0,
        WatchPriority.MEDIUM: 1,
        WatchPriority.LOW: 2,
    }[brief.watch_priority]
    return (priority_rank, -brief.risk_rank, -brief.earnings_gate_rank, brief.ticker)


def _role_label(priority: WatchPriority) -> str:
    if priority is WatchPriority.HIGH:
        return "CORE"
    if priority is WatchPriority.MEDIUM:
        return "SATELLITE"
    return "SANDBOX"


def _risk_level(*, risk_points: int) -> tuple[str, int]:
    if risk_points <= 1:
        return ("RL0", 0)
    if risk_points == 2:
        return ("RL1", 1)
    if risk_points == 3:
        return ("RL2", 2)
    return ("RL3", 3)


def _earnings_gate(*, earnings_days: int | None, config: PhaseAHoldingsConfig) -> tuple[str, int]:
    if earnings_days is None:
        return ("E1(不明)", 1)
    if earnings_days <= config.earnings_gate_e3_days:
        return ("E3", 3)
    if earnings_days <= config.earnings_gate_e2_days:
        return ("E2", 2)
    if earnings_days <= config.earnings_gate_e1_days:
        return ("E1", 1)
    return ("E0", 0)


def _action_candidates(*, risk_rank: int, earnings_gate_rank: int) -> list[str]:
    actions: list[str] = []
    if earnings_gate_rank >= 3:
        actions.append("決算直前のため新規買い増しは停止")
    elif earnings_gate_rank == 2:
        actions.append("買い増しは1/3までに制限")
    elif earnings_gate_rank == 1 and risk_rank <= 1:
        actions.append("買い増しは分割で第1弾のみ検討")

    if risk_rank >= 3:
        actions.append("縮小または退避ラインの確認を優先")
    elif risk_rank == 2:
        actions.append("損失許容ラインと撤退条件を再確認")
    elif risk_rank <= 1 and earnings_gate_rank == 0:
        actions.append("保有継続（定点観測）")

    if not actions:
        actions.append("材料待ち（様子見）")
    return actions


def _format_phase_a_message(*, brief: PhaseAHoldingBrief, trade_date: str, config: PhaseAHoldingsConfig) -> str:
    earnings_text = _fmt_earnings_days(brief.earnings_days)
    return "\n".join(
        [
            f"【フェイズA保有】{brief.role_label} {brief.ticker} {brief.company_name}",
            f"日付: {trade_date}",
            f"RL: {brief.risk_level}（{brief.risk_points}点） / 決算ゲート: {brief.earnings_gate_code}（{earnings_text}）",
            f"価格: {_fmt_price(brief.latest_close)} / 日次: {_fmt_pct(brief.day_change_pct)} / 週次: {_fmt_pct(brief.week_change_pct)}",
            (
                f"トレンド: MA{config.trend_ma_short_days}={_fmt_price(brief.ma_short)} / "
                f"MA{config.trend_ma_long_days}={_fmt_price(brief.ma_long)} / 判定: {brief.trend_label}"
            ),
            f"根拠: {' / '.join(brief.risk_reasons)}",
            f"候補アクション: {' / '.join(brief.action_candidates)}",
        ]
    )


def _dispatch_with_cooldown(
    *,
    ticker: str,
    body: str,
    condition_key: str,
    is_strong: bool,
    now_iso: str,
    cooldown_hours: int,
    channel: str,
    data_source: str | None,
    data_fetched_at: str | None,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
) -> tuple[int, int]:
    normalized_ticker = normalize_ticker(ticker)
    recent = notification_log_repo.list_recent(normalized_ticker, limit=100)
    decision = evaluate_cooldown(
        now_iso=now_iso,
        cooldown_hours=cooldown_hours,
        candidate_ticker=normalized_ticker,
        candidate_category=_PHASE_A_CATEGORY,
        candidate_condition_key=condition_key,
        candidate_is_strong=is_strong,
        recent_entries=recent,
    )
    if not decision.should_send:
        LOGGER.info(
            "フェイズA通知スキップ: ticker=%s reason=%s condition=%s",
            normalized_ticker,
            decision.reason,
            condition_key,
        )
        return (0, 1)

    sender.send(body)
    log_entry = NotificationLogEntry(
        entry_id=_notification_id(
            ticker=normalized_ticker,
            category=_PHASE_A_CATEGORY,
            condition_key=condition_key,
            channel=channel,
            sent_at=now_iso,
        ),
        ticker=normalized_ticker,
        category=_PHASE_A_CATEGORY,
        condition_key=condition_key,
        sent_at=now_iso,
        channel=channel,
        payload_hash=sha1(body.encode("utf-8")).hexdigest(),
        is_strong=is_strong,
        body=body,
        data_source=data_source,
        data_fetched_at=data_fetched_at,
    )
    notification_log_repo.append(log_entry)
    return (1, 0)


def _notification_id(*, ticker: str, category: str, condition_key: str, channel: str, sent_at: str) -> str:
    raw = f"{ticker}|{category}|{condition_key}|{channel}|{sent_at}"
    return sha1(raw.encode("utf-8")).hexdigest()


def _is_channel_enabled(*, item: WatchlistItem, channel: str) -> bool:
    normalized = channel.strip().upper()
    if item.notify_channel is NotifyChannel.OFF:
        return False
    if normalized.startswith("DISCORD"):
        return item.notify_channel is NotifyChannel.DISCORD
    return False


def _should_dispatch_for_timing(notify_timing: NotifyTiming, execution_mode: NotificationExecutionMode) -> bool:
    if notify_timing is NotifyTiming.OFF:
        return False
    if execution_mode is NotificationExecutionMode.ALL:
        return True
    if execution_mode is NotificationExecutionMode.DAILY:
        return notify_timing is NotifyTiming.IMMEDIATE
    return notify_timing is NotifyTiming.AT_21


def _resolve_earnings_days(*, trade_date: str, earnings_date: str | None) -> int | None:
    if not earnings_date:
        return None
    try:
        base_date = date.fromisoformat(trade_date)
        target_date = date.fromisoformat(earnings_date)
    except ValueError:
        return None
    return max((target_date - base_date).days, 0)


def _change_pct(*, current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return ((current - previous) / previous) * 100.0


def _rolling_mean(*, values: list[float], window: int) -> float | None:
    if window <= 0:
        return None
    if len(values) < window:
        return None
    return float(mean(values[:window]))


def _fmt_price(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f}円"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.1f}%"


def _fmt_earnings_days(value: int | None) -> str:
    if value is None:
        return "不明"
    if value <= 0:
        return "当日"
    return f"{value}日"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

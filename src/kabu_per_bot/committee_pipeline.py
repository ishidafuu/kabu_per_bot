from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
import logging
from typing import Protocol

from kabu_per_bot.baseline_research import BaselineResearchRecord
from kabu_per_bot.committee import CommitteeContext, CommitteeEvaluation, CommitteeEvaluationEngine
from kabu_per_bot.market_data import MarketDataError, MarketDataSource
from kabu_per_bot.metrics import DailyMetric, MetricMedians
from kabu_per_bot.notification import format_committee_evaluation_message
from kabu_per_bot.pipeline import NotificationExecutionMode, PipelineResult
from kabu_per_bot.signal import NotificationLogEntry, evaluate_cooldown
from kabu_per_bot.watchlist import EvaluationNotifyMode, NotifyChannel, NotifyTiming, WatchlistItem


LOGGER = logging.getLogger(__name__)


class MessageSender(Protocol):
    def send(self, message: str) -> None:
        """Send outbound message."""


class DailyMetricsRepository(Protocol):
    def list_recent(self, ticker: str, *, limit: int) -> list[DailyMetric]:
        """Get recent metric rows."""


class MetricMediansRepository(Protocol):
    def list_recent(self, ticker: str, *, limit: int) -> list[MetricMedians]:
        """Get recent medians rows."""


class NotificationLogRepository(Protocol):
    def append(self, entry: NotificationLogEntry) -> None:
        """Persist notification log."""

    def list_recent(self, ticker: str, *, limit: int = 100) -> list[NotificationLogEntry]:
        """Get recent notification log rows."""


class BaselineResearchRepository(Protocol):
    def get_latest(self, ticker: str) -> BaselineResearchRecord | None:
        """Get latest baseline research."""


@dataclass(frozen=True)
class CommitteePipelineConfig:
    trade_date: str
    now_iso: str
    cooldown_hours: int
    channel: str = "DISCORD_DAILY"
    execution_mode: NotificationExecutionMode = NotificationExecutionMode.DAILY
    metrics_lookback_days: int = 80


@dataclass(frozen=True)
class _EvaluationCandidate:
    item: WatchlistItem
    evaluation: CommitteeEvaluation
    data_source: str | None
    data_fetched_at: str | None


def run_committee_pipeline(
    *,
    watchlist_items: list[WatchlistItem],
    market_data_source: MarketDataSource,
    daily_metrics_repo: DailyMetricsRepository,
    medians_repo: MetricMediansRepository,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    config: CommitteePipelineConfig,
    engine: CommitteeEvaluationEngine | None = None,
    baseline_repository: BaselineResearchRepository | None = None,
) -> PipelineResult:
    evaluator = engine or CommitteeEvaluationEngine()
    candidates: list[_EvaluationCandidate] = []
    result = PipelineResult()

    for item in watchlist_items:
        if not item.is_active or not item.evaluation_enabled:
            continue
        if not _is_channel_enabled(item=item, channel=config.channel):
            continue
        if not _should_dispatch_for_timing(item.notify_timing, config.execution_mode):
            continue

        try:
            recent_metrics = daily_metrics_repo.list_recent(item.ticker, limit=config.metrics_lookback_days)
            latest_metric = recent_metrics[0] if recent_metrics else None
            latest_medians_rows = medians_repo.list_recent(item.ticker, limit=1)
            latest_medians = latest_medians_rows[0] if latest_medians_rows else None
            snapshot = None
            data_source: str | None = None
            data_fetched_at: str | None = None
            try:
                snapshot = market_data_source.fetch_snapshot(item.ticker)
                data_source = snapshot.source
                data_fetched_at = snapshot.fetched_at
            except MarketDataError as exc:
                LOGGER.warning("委員会評価の市場データ取得失敗: ticker=%s error=%s", item.ticker, exc)
            baseline = baseline_repository.get_latest(item.ticker) if baseline_repository is not None else None

            context = CommitteeContext(
                ticker=item.ticker,
                company_name=item.name,
                trade_date=config.trade_date,
                metric_type=item.metric_type,
                latest_metric=latest_metric,
                recent_metrics=tuple(recent_metrics),
                latest_medians=latest_medians,
                market_snapshot=snapshot,
                baseline_summary=baseline.summary if baseline is not None else None,
                baseline_reliability_score=baseline.reliability_score if baseline is not None else None,
                baseline_updated_at=baseline.updated_at if baseline is not None else None,
            )
            evaluation = evaluator.evaluate(context)
            candidates.append(
                _EvaluationCandidate(
                    item=item,
                    evaluation=evaluation,
                    data_source=data_source,
                    data_fetched_at=data_fetched_at,
                )
            )
            result = result.merge(PipelineResult(processed_tickers=1))
        except Exception as exc:
            LOGGER.exception("委員会評価処理失敗: ticker=%s error=%s", item.ticker, exc)
            result = result.merge(PipelineResult(processed_tickers=1, errors=1))

    ranked = sorted(
        candidates,
        key=lambda row: (row.evaluation.strength, row.evaluation.confidence, row.item.ticker),
        reverse=True,
    )
    rank_map: dict[str, int] = {row.item.ticker: idx + 1 for idx, row in enumerate(ranked)}

    for candidate in ranked:
        mode = candidate.item.evaluation_notify_mode
        rank = rank_map[candidate.item.ticker]
        if not _is_notify_target(candidate=candidate, mode=mode, rank=rank):
            result = result.merge(PipelineResult(skipped_notifications=1))
            continue
        try:
            message = format_committee_evaluation_message(evaluation=candidate.evaluation)
            sent, skipped = _dispatch_with_cooldown(
                ticker=candidate.item.ticker,
                message=message.body,
                category=message.category,
                condition_key=message.condition_key,
                is_strong=message.is_strong,
                now_iso=config.now_iso,
                cooldown_hours=config.cooldown_hours,
                channel=config.channel,
                data_source=candidate.data_source,
                data_fetched_at=candidate.data_fetched_at,
                notification_log_repo=notification_log_repo,
                sender=sender,
                confidence=candidate.evaluation.confidence,
                strength=candidate.evaluation.strength,
                lens_strengths={lens.key.value: lens.strength for lens in candidate.evaluation.lenses},
                lens_confidences={lens.key.value: lens.confidence for lens in candidate.evaluation.lenses},
            )
            result = result.merge(PipelineResult(sent_notifications=sent, skipped_notifications=skipped))
        except Exception as exc:
            LOGGER.exception("委員会評価通知失敗: ticker=%s error=%s", candidate.item.ticker, exc)
            result = result.merge(PipelineResult(errors=1))

    return result


def _is_notify_target(
    *,
    candidate: _EvaluationCandidate,
    mode: EvaluationNotifyMode,
    rank: int,
) -> bool:
    if mode is EvaluationNotifyMode.ALL:
        return True
    if mode is EvaluationNotifyMode.TOP_N:
        return rank <= candidate.item.evaluation_top_n
    return candidate.evaluation.strength >= candidate.item.evaluation_min_strength


def _dispatch_with_cooldown(
    *,
    ticker: str,
    message: str,
    category: str,
    condition_key: str,
    is_strong: bool,
    now_iso: str,
    cooldown_hours: int,
    channel: str,
    data_source: str | None,
    data_fetched_at: str | None,
    notification_log_repo: NotificationLogRepository,
    sender: MessageSender,
    confidence: int,
    strength: int,
    lens_strengths: dict[str, int],
    lens_confidences: dict[str, int],
) -> tuple[int, int]:
    recent = notification_log_repo.list_recent(ticker, limit=100)
    decision = evaluate_cooldown(
        now_iso=now_iso,
        cooldown_hours=cooldown_hours,
        candidate_ticker=ticker,
        candidate_category=category,
        candidate_condition_key=condition_key,
        candidate_is_strong=is_strong,
        recent_entries=recent,
    )
    if not decision.should_send:
        return (0, 1)

    sender.send(message)
    entry = NotificationLogEntry(
        entry_id=_notification_id(ticker=ticker, category=category, condition_key=condition_key, channel=channel, sent_at=now_iso),
        ticker=ticker,
        category=category,
        condition_key=condition_key,
        sent_at=now_iso,
        channel=channel,
        payload_hash=sha1(message.encode("utf-8")).hexdigest(),
        is_strong=is_strong,
        body=message,
        data_source=data_source,
        data_fetched_at=data_fetched_at,
        evaluation_confidence=confidence,
        evaluation_strength=strength,
        evaluation_lens_strengths=lens_strengths,
        evaluation_lens_confidences=lens_confidences,
    )
    notification_log_repo.append(entry)
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


def _should_dispatch_for_timing(
    notify_timing: NotifyTiming,
    execution_mode: NotificationExecutionMode | str,
) -> bool:
    mode = _normalize_execution_mode(execution_mode)
    if notify_timing is NotifyTiming.OFF:
        return False
    if mode is NotificationExecutionMode.ALL:
        return True
    if mode is NotificationExecutionMode.DAILY:
        return notify_timing is NotifyTiming.IMMEDIATE
    return notify_timing is NotifyTiming.AT_21


def _normalize_execution_mode(execution_mode: NotificationExecutionMode | str) -> NotificationExecutionMode:
    if isinstance(execution_mode, NotificationExecutionMode):
        return execution_mode
    return NotificationExecutionMode(str(execution_mode).strip().upper())


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

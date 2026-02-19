#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.grok_sns_settings import GrokSnsSettings
from kabu_per_bot.intelligence import CompositeIntelSource, GrokPromptIntelSource, IRWebsiteIntelSource, VertexGeminiAiAnalyzer
from kabu_per_bot.intelligence_pipeline import IntelligencePipelineConfig, run_intelligence_pipeline
from kabu_per_bot.pipeline import NotificationExecutionMode, PipelineResult
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings, resolve_runtime_settings
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_global_settings_repository import FirestoreGlobalSettingsRepository
from kabu_per_bot.storage.firestore_intel_seen_repository import FirestoreIntelSeenRepository
from kabu_per_bot.storage.firestore_notification_log_repository import FirestoreNotificationLogRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository


LOGGER = logging.getLogger(__name__)
DISCORD_WEBHOOK_DEFAULT_ENV = "DISCORD_WEBHOOK_URL"
DISCORD_WEBHOOK_INTELLIGENCE_ENV = "DISCORD_WEBHOOK_URL_INTELLIGENCE"
DISCORD_WEBHOOK_INTELLIGENCE_IR_ENV = "DISCORD_WEBHOOK_URL_INTELLIGENCE_IR"
DISCORD_WEBHOOK_INTELLIGENCE_SNS_ENV = "DISCORD_WEBHOOK_URL_INTELLIGENCE_SNS"
DISCORD_INTELLIGENCE_IR_CHANNEL = "DISCORD_INTELLIGENCE_IR"
DISCORD_INTELLIGENCE_SNS_CHANNEL = "DISCORD_INTELLIGENCE_SNS"


class StdoutSender:
    def send(self, message: str) -> None:
        print("----- notification -----")
        print(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run IR/SNS intelligence notification job.")
    parser.add_argument(
        "--now-iso",
        default=None,
        help="Current time in ISO8601 with timezone (e.g. 2026-02-14T21:00:00+09:00). Default: now(UTC)",
    )
    parser.add_argument(
        "--execution-mode",
        choices=("all", "daily", "at_21"),
        default="all",
        help="Dispatch filter mode. all=daily+21, daily=IMMEDIATE only, at_21=AT_21 only.",
    )
    parser.add_argument(
        "--intel-source",
        choices=("all", "ir_only", "grok_only"),
        default="all",
        help="Intelligence source scope. all=IR+Grok, ir_only=IR only, grok_only=Grok only.",
    )
    parser.add_argument(
        "--respect-grok-schedule",
        action="store_true",
        help=(
            "When enabled, run pipeline only at scheduled Grok minute in JST. "
            "Recommended for Cloud Scheduler every-minute trigger."
        ),
    )
    parser.add_argument(
        "--discord-webhook-url",
        default=_resolve_discord_webhook_default(DISCORD_WEBHOOK_INTELLIGENCE_ENV),
        help=(
            "Discord webhook URL (共通fallback)。Required unless --stdout is set. "
            f"Default: {DISCORD_WEBHOOK_INTELLIGENCE_ENV} (fallback: {DISCORD_WEBHOOK_DEFAULT_ENV})."
        ),
    )
    parser.add_argument(
        "--discord-webhook-url-ir",
        default=_resolve_discord_webhook_default(
            DISCORD_WEBHOOK_INTELLIGENCE_IR_ENV,
            DISCORD_WEBHOOK_INTELLIGENCE_ENV,
        ),
        help=(
            "Discord webhook URL for IR notifications. Required unless --stdout is set and IR scope is selected. "
            f"Default: {DISCORD_WEBHOOK_INTELLIGENCE_IR_ENV} "
            f"(fallback: {DISCORD_WEBHOOK_INTELLIGENCE_ENV} -> {DISCORD_WEBHOOK_DEFAULT_ENV})."
        ),
    )
    parser.add_argument(
        "--discord-webhook-url-sns",
        default=_resolve_discord_webhook_default(
            DISCORD_WEBHOOK_INTELLIGENCE_SNS_ENV,
            DISCORD_WEBHOOK_INTELLIGENCE_ENV,
        ),
        help=(
            "Discord webhook URL for SNS/AI notifications. "
            "Required unless --stdout is set and SNS scope is selected. "
            f"Default: {DISCORD_WEBHOOK_INTELLIGENCE_SNS_ENV} "
            f"(fallback: {DISCORD_WEBHOOK_INTELLIGENCE_ENV} -> {DISCORD_WEBHOOK_DEFAULT_ENV})."
        ),
    )
    parser.add_argument("--stdout", action="store_true", help="Send notifications to stdout.")
    return parser.parse_args()


def _resolve_discord_webhook_default(primary_env_key: str, *fallback_env_keys: str) -> str:
    for env_key in (primary_env_key, *fallback_env_keys):
        value = os.environ.get(env_key, "").strip()
        if value:
            return value
    return os.environ.get(DISCORD_WEBHOOK_DEFAULT_ENV, "").strip()


def _create_firestore_client(*, project_id: str):
    try:
        from google.cloud import firestore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-cloud-firestore が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc
    return firestore.Client(project=project_id or None)


def _resolve_scope_sender(args: argparse.Namespace, *, scope: str):
    if args.stdout:
        LOGGER.info("送信先: stdout (scope=%s)", scope)
        return StdoutSender()

    webhook_url = _resolve_scope_webhook_url(args, scope=scope)
    if not webhook_url:
        if scope == "ir_only":
            raise ValueError(
                "IR通知向け Discord webhook URL が必要です。"
                "--discord-webhook-url-ir または "
                f"{DISCORD_WEBHOOK_INTELLIGENCE_IR_ENV}/"
                f"{DISCORD_WEBHOOK_INTELLIGENCE_ENV}/"
                f"{DISCORD_WEBHOOK_DEFAULT_ENV} を設定してください。"
            )
        raise ValueError(
            "SNS通知向け Discord webhook URL が必要です。"
            "--discord-webhook-url-sns または "
            f"{DISCORD_WEBHOOK_INTELLIGENCE_SNS_ENV}/"
            f"{DISCORD_WEBHOOK_INTELLIGENCE_ENV}/"
            f"{DISCORD_WEBHOOK_DEFAULT_ENV} を設定してください。"
        )
    LOGGER.info("送信先: Discord webhook (scope=%s channel=%s)", scope, _channel_for_scope(scope))
    return DiscordNotifier(webhook_url)


def _resolve_scope_webhook_url(args: argparse.Namespace, *, scope: str) -> str:
    common = str(getattr(args, "discord_webhook_url", "")).strip()
    ir = str(getattr(args, "discord_webhook_url_ir", "")).strip()
    sns = str(getattr(args, "discord_webhook_url_sns", "")).strip()
    if scope == "ir_only":
        return ir or common
    if scope == "grok_only":
        return sns or common
    raise ValueError(f"unsupported scope: {scope}")


def _channel_for_scope(scope: str) -> str:
    if scope == "ir_only":
        return DISCORD_INTELLIGENCE_IR_CHANNEL
    if scope == "grok_only":
        return DISCORD_INTELLIGENCE_SNS_CHANNEL
    raise ValueError(f"unsupported scope: {scope}")


def _resolve_now_utc_iso(*, now_iso: str | None) -> str:
    if now_iso is None:
        return datetime.now(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(now_iso)
    if parsed.tzinfo is None:
        raise ValueError("now_iso must include timezone offset, e.g. '+09:00'.")
    return parsed.astimezone(timezone.utc).isoformat()


def _resolve_execution_mode(raw: str) -> NotificationExecutionMode:
    mapping = {
        "all": NotificationExecutionMode.ALL,
        "daily": NotificationExecutionMode.DAILY,
        "at_21": NotificationExecutionMode.AT_21,
    }
    return mapping[raw]


def _default_grok_sns_settings(*, settings) -> GrokSnsSettings:
    return GrokSnsSettings(
        enabled=settings.grok_sns_enabled,
        scheduled_time=settings.grok_sns_scheduled_time,
        per_ticker_cooldown_hours=settings.grok_sns_per_ticker_cooldown_hours,
        prompt_template=settings.grok_sns_prompt_template,
    )


def _resolve_runtime_config(*, settings, client):
    default_grok_sns_settings = _default_grok_sns_settings(settings=settings)
    try:
        repository = FirestoreGlobalSettingsRepository(client)
        runtime_settings = resolve_runtime_settings(
            default_cooldown_hours=settings.cooldown_hours,
            default_intel_notification_max_age_days=settings.intel_notification_max_age_days,
            default_grok_sns_settings=default_grok_sns_settings,
            global_settings=repository.get_global_settings(),
        )
        LOGGER.info(
            "クールダウン設定: %s時間 (source=%s)",
            runtime_settings.cooldown_hours,
            runtime_settings.source,
        )
        LOGGER.info(
            "IR/SNS通知対象期間: %s日",
            runtime_settings.intel_notification_max_age_days,
        )
        LOGGER.info(
            "Grok SNS設定: enabled=%s schedule=%s cooldown=%s時間",
            runtime_settings.grok_sns_settings.enabled,
            runtime_settings.grok_sns_settings.scheduled_time,
            runtime_settings.grok_sns_settings.per_ticker_cooldown_hours,
        )
        return runtime_settings
    except Exception as exc:
        LOGGER.warning("全体設定の取得に失敗したため環境変数設定を使用: %s", exc)
        return resolve_runtime_settings(
            default_cooldown_hours=settings.cooldown_hours,
            default_intel_notification_max_age_days=settings.intel_notification_max_age_days,
            default_grok_sns_settings=default_grok_sns_settings,
            global_settings=GlobalRuntimeSettings(),
        )


def _build_intel_source(
    *,
    settings,
    runtime_settings,
    intel_source: str,
    now_iso: str | None = None,
    notification_log_repo=None,
) -> CompositeIntelSource:
    include_ir = intel_source in ("all", "ir_only")
    include_grok = intel_source in ("all", "grok_only")
    sources = []
    if include_ir:
        sources.append(IRWebsiteIntelSource())

    if include_grok and runtime_settings.grok_sns_settings.enabled:
        scheduled_time = runtime_settings.grok_sns_settings.scheduled_time
        if _is_scheduled_grok_time(now_iso=now_iso, scheduled_time=scheduled_time):
            fetch_gate = None
            if notification_log_repo is not None:
                fetch_gate = _create_grok_fetch_gate(
                    notification_log_repo=notification_log_repo,
                    cooldown_hours=runtime_settings.grok_sns_settings.per_ticker_cooldown_hours,
                )
            sources.append(
                GrokPromptIntelSource(
                    api_key=settings.grok_api_key,
                    api_base_url=settings.grok_api_base_url,
                    model=settings.grok_model_fast,
                    reasoning_model=settings.grok_model_reasoning,
                    prompt_template=runtime_settings.grok_sns_settings.prompt_template,
                    fetch_gate=fetch_gate,
                )
            )
        else:
            LOGGER.info("Grok SNS取得はスケジュール外のためスキップします（scheduled_time=%s JST）", scheduled_time)
    elif include_grok:
        LOGGER.info("Grok SNS取得は無効です（global settings）。")
    return CompositeIntelSource(tuple(sources))


def _is_grok_in_scope(intel_source: str) -> bool:
    return intel_source in ("all", "grok_only")


def _is_scheduled_grok_time(*, now_iso: str | None, scheduled_time: str) -> bool:
    if now_iso is None:
        return True
    parsed = datetime.fromisoformat(now_iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    jst = parsed.astimezone(ZoneInfo("Asia/Tokyo"))
    return f"{jst.hour:02d}:{jst.minute:02d}" == scheduled_time


def _should_run_by_grok_schedule(*, now_iso: str, runtime_settings) -> bool:
    if not runtime_settings.grok_sns_settings.enabled:
        LOGGER.info("Grok SNS取得は無効のため処理をスキップします。")
        return False
    scheduled_time = runtime_settings.grok_sns_settings.scheduled_time
    if not _is_scheduled_grok_time(now_iso=now_iso, scheduled_time=scheduled_time):
        LOGGER.info("Grok SNS定時外のため処理をスキップします（scheduled_time=%s JST）", scheduled_time)
        return False
    return True


def _create_grok_fetch_gate(*, notification_log_repo, cooldown_hours: int):
    def gate(item, now_iso: str) -> bool:
        if cooldown_hours <= 0:
            return True
        now_dt = _parse_iso_utc(now_iso)
        try:
            recent_logs = notification_log_repo.list_recent(item.ticker, limit=100)
        except Exception as exc:
            LOGGER.warning("Grok取得抑制判定に失敗したため取得を継続: ticker=%s error=%s", item.ticker, exc)
            return True

        for entry in recent_logs:
            category = str(getattr(entry, "category", "")).strip()
            if category != "SNS注目":
                continue
            sent_at = _parse_iso_utc_or_none(getattr(entry, "sent_at", None))
            if sent_at is None:
                continue
            if now_dt - sent_at < timedelta(hours=cooldown_hours):
                LOGGER.info("Grok SNS取得をスキップ: ticker=%s reason=%s時間クールダウン中", item.ticker, cooldown_hours)
                return False
        return True

    return gate


def _parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_iso_utc_or_none(value) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return _parse_iso_utc(text)
    except ValueError:
        return None


def _run_source_scoped_pipeline(
    *,
    scope: str,
    settings,
    runtime_settings,
    now_iso: str,
    watchlist_items,
    analyzer,
    seen_repo,
    notification_log_repo,
    sender,
    channel: str,
    execution_mode: NotificationExecutionMode,
) -> PipelineResult:
    source = _build_intel_source(
        settings=settings,
        runtime_settings=runtime_settings,
        intel_source=scope,
        now_iso=now_iso,
        notification_log_repo=notification_log_repo,
    )
    if not source.sources:
        LOGGER.info("IR/SNSパイプラインをスキップ: scope=%s reason=sourceなし", scope)
        return PipelineResult()

    result = run_intelligence_pipeline(
        watchlist_items=watchlist_items,
        source=source,
        analyzer=analyzer,
        seen_repo=seen_repo,
        notification_log_repo=notification_log_repo,
        sender=sender,
        config=IntelligencePipelineConfig(
            cooldown_hours=runtime_settings.cooldown_hours,
            now_iso=now_iso,
            intel_notification_max_age_days=runtime_settings.intel_notification_max_age_days,
            channel=channel,
            execution_mode=execution_mode,
            ai_global_enabled=settings.ai_notifications_enabled,
        ),
    )
    LOGGER.info(
        "IR/SNSパイプライン結果: scope=%s processed=%s sent=%s skipped=%s errors=%s",
        scope,
        result.processed_tickers,
        result.sent_notifications,
        result.skipped_notifications,
        result.errors,
    )
    return result


def _merge_scoped_results(results: list[PipelineResult]) -> PipelineResult:
    if not results:
        return PipelineResult()
    return PipelineResult(
        processed_tickers=max(result.processed_tickers for result in results),
        sent_notifications=sum(result.sent_notifications for result in results),
        skipped_notifications=sum(result.skipped_notifications for result in results),
        errors=sum(result.errors for result in results),
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    settings = load_settings()
    now_iso = _resolve_now_utc_iso(now_iso=args.now_iso)
    client = _create_firestore_client(project_id=settings.firestore_project_id)
    runtime_settings = _resolve_runtime_config(settings=settings, client=client)
    if getattr(args, "respect_grok_schedule", False) and _is_grok_in_scope(args.intel_source):
        if not _should_run_by_grok_schedule(now_iso=now_iso, runtime_settings=runtime_settings):
            print(json.dumps(PipelineResult().__dict__, ensure_ascii=False))
            return 0
    scopes = ("ir_only", "grok_only") if args.intel_source == "all" else (args.intel_source,)
    scope_senders = {scope: _resolve_scope_sender(args, scope=scope) for scope in scopes}

    watchlist_repo = FirestoreWatchlistRepository(client)
    log_repo = FirestoreNotificationLogRepository(client)
    seen_repo = FirestoreIntelSeenRepository(client)
    watchlist_items = watchlist_repo.list_all()
    analyzer = VertexGeminiAiAnalyzer(
        project_id=settings.firestore_project_id,
        location=settings.vertex_ai_location,
        model=settings.vertex_ai_model,
    )
    execution_mode = _resolve_execution_mode(args.execution_mode)

    scoped_results: list[PipelineResult] = []
    for scope in scopes:
        channel = _channel_for_scope(scope)
        scoped_results.append(
            _run_source_scoped_pipeline(
                scope=scope,
                settings=settings,
                runtime_settings=runtime_settings,
                now_iso=now_iso,
                watchlist_items=watchlist_items,
                analyzer=analyzer,
                seen_repo=seen_repo,
                notification_log_repo=log_repo,
                sender=scope_senders[scope],
                channel=channel,
                execution_mode=execution_mode,
            )
        )
    result = _merge_scoped_results(scoped_results)
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.exception("intelligence job failed: %s", exc)
        raise SystemExit(1) from exc

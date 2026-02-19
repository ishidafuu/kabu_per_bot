#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from kabu_per_bot.discord_notifier import DiscordNotifier
from kabu_per_bot.grok_sns_settings import GrokSnsSettings
from kabu_per_bot.intelligence import CompositeIntelSource, GrokPromptIntelSource, IRWebsiteIntelSource, VertexGeminiAiAnalyzer
from kabu_per_bot.intelligence_pipeline import IntelligencePipelineConfig, run_intelligence_pipeline
from kabu_per_bot.pipeline import NotificationExecutionMode
from kabu_per_bot.runtime_settings import GlobalRuntimeSettings, resolve_runtime_settings
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_global_settings_repository import FirestoreGlobalSettingsRepository
from kabu_per_bot.storage.firestore_intel_seen_repository import FirestoreIntelSeenRepository
from kabu_per_bot.storage.firestore_notification_log_repository import FirestoreNotificationLogRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository


LOGGER = logging.getLogger(__name__)


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
        "--discord-webhook-url",
        default=os.environ.get("DISCORD_WEBHOOK_URL", "").strip(),
        help="Discord webhook URL. Required unless --stdout is set.",
    )
    parser.add_argument("--stdout", action="store_true", help="Send notifications to stdout.")
    return parser.parse_args()


def _create_firestore_client(*, project_id: str):
    try:
        from google.cloud import firestore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-cloud-firestore が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc
    return firestore.Client(project=project_id or None)


def _resolve_sender(args: argparse.Namespace):
    if args.stdout:
        LOGGER.info("送信先: stdout")
        return StdoutSender()
    webhook_url = args.discord_webhook_url.strip()
    if not webhook_url:
        raise ValueError("Discord webhook URL が必要です。--discord-webhook-url か DISCORD_WEBHOOK_URL を設定してください。")
    LOGGER.info("送信先: Discord webhook")
    return DiscordNotifier(webhook_url)


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
            default_grok_sns_settings=default_grok_sns_settings,
            global_settings=repository.get_global_settings(),
        )
        LOGGER.info(
            "クールダウン設定: %s時間 (source=%s)",
            runtime_settings.cooldown_hours,
            runtime_settings.source,
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
            default_grok_sns_settings=default_grok_sns_settings,
            global_settings=GlobalRuntimeSettings(),
        )


def _build_intel_source(*, settings, runtime_settings, now_iso: str | None = None) -> CompositeIntelSource:
    sources = [IRWebsiteIntelSource()]
    if runtime_settings.grok_sns_settings.enabled:
        scheduled_time = runtime_settings.grok_sns_settings.scheduled_time
        if _is_scheduled_grok_time(now_iso=now_iso, scheduled_time=scheduled_time):
            sources.append(
                GrokPromptIntelSource(
                    api_key=settings.grok_api_key,
                    api_base_url=settings.grok_api_base_url,
                    model=settings.grok_model_fast,
                    reasoning_model=settings.grok_model_reasoning,
                    prompt_template=runtime_settings.grok_sns_settings.prompt_template,
                )
            )
        else:
            LOGGER.info("Grok SNS取得はスケジュール外のためスキップします（scheduled_time=%s JST）", scheduled_time)
    else:
        LOGGER.info("Grok SNS取得は無効です（global settings）。")
    return CompositeIntelSource(tuple(sources))


def _is_scheduled_grok_time(*, now_iso: str | None, scheduled_time: str) -> bool:
    if now_iso is None:
        return True
    parsed = datetime.fromisoformat(now_iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    jst = parsed.astimezone(ZoneInfo("Asia/Tokyo"))
    return f"{jst.hour:02d}:{jst.minute:02d}" == scheduled_time


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    settings = load_settings()
    sender = _resolve_sender(args)
    now_iso = _resolve_now_utc_iso(now_iso=args.now_iso)
    client = _create_firestore_client(project_id=settings.firestore_project_id)
    runtime_settings = _resolve_runtime_config(settings=settings, client=client)
    watchlist_repo = FirestoreWatchlistRepository(client)
    log_repo = FirestoreNotificationLogRepository(client)
    seen_repo = FirestoreIntelSeenRepository(client)
    source = _build_intel_source(settings=settings, runtime_settings=runtime_settings, now_iso=now_iso)
    result = run_intelligence_pipeline(
        watchlist_items=watchlist_repo.list_all(),
        source=source,
        analyzer=VertexGeminiAiAnalyzer(
            project_id=settings.firestore_project_id,
            location=settings.vertex_ai_location,
            model=settings.vertex_ai_model,
        ),
        seen_repo=seen_repo,
        notification_log_repo=log_repo,
        sender=sender,
        config=IntelligencePipelineConfig(
            cooldown_hours=runtime_settings.cooldown_hours,
            now_iso=now_iso,
            execution_mode=_resolve_execution_mode(args.execution_mode),
            ai_global_enabled=settings.ai_notifications_enabled,
        ),
    )
    print(json.dumps(result.__dict__, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.exception("intelligence job failed: %s", exc)
        raise SystemExit(1) from exc

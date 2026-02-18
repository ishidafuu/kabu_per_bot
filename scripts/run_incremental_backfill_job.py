#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import logging
import os
from zoneinfo import ZoneInfo

from kabu_per_bot.backfill_service import (
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    DEFAULT_OVERLAP_DAYS,
    backfill_ticker_from_jquants,
    refresh_latest_medians_and_signal,
    resolve_incremental_from_date,
)
from kabu_per_bot.jquants_v2 import JQuantsV2Client
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_daily_metrics_repository import FirestoreDailyMetricsRepository
from kabu_per_bot.storage.firestore_metric_medians_repository import FirestoreMetricMediansRepository
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date
from kabu_per_bot.storage.firestore_signal_state_repository import FirestoreSignalStateRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository
from kabu_per_bot.watchlist import WatchlistItem


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncrementalBackfillResult:
    ticker: str
    from_date: str
    to_date: str
    generated: int
    upserted: int
    errors: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run incremental daily_metrics backfill from J-Quants API v2.")
    parser.add_argument(
        "--to-date",
        default=None,
        help="End date (YYYY-MM-DD or YYYYMMDD). Default: today(JST).",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma separated ticker list. Example: 3984:TSE,6238:TSE. Default: all active watchlist.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("JQUANTS_API_KEY", "").strip(),
        help="J-Quants API v2 key. Default: JQUANTS_API_KEY env.",
    )
    parser.add_argument(
        "--initial-lookback-days",
        type=int,
        default=DEFAULT_INITIAL_LOOKBACK_DAYS,
        help=f"Lookback days when ticker has no history (default: {DEFAULT_INITIAL_LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--overlap-days",
        type=int,
        default=DEFAULT_OVERLAP_DAYS,
        help=f"Overlap days from latest trade date (default: {DEFAULT_OVERLAP_DAYS}).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only. Do not write Firestore.")
    return parser.parse_args()


def _create_firestore_client(*, project_id: str):
    try:
        from google.cloud import firestore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "google-cloud-firestore が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc
    return firestore.Client(project=project_id or None)


def _parse_target_tickers(raw: str) -> list[str]:
    if not raw.strip():
        return []
    values = []
    for entry in raw.split(","):
        ticker = entry.strip()
        if not ticker:
            continue
        values.append(normalize_ticker(ticker))
    return values


def _select_watchlist_items(all_items: list[WatchlistItem], *, target_tickers: list[str]) -> list[WatchlistItem]:
    active_items = [item for item in all_items if item.is_active]
    if not target_tickers:
        return sorted(active_items, key=lambda item: item.ticker)
    index = {item.ticker: item for item in active_items}
    selected: list[WatchlistItem] = []
    missing: list[str] = []
    for ticker in target_tickers:
        item = index.get(ticker)
        if item is None:
            missing.append(ticker)
            continue
        selected.append(item)
    if missing:
        raise ValueError(f"watchlistに存在しない、または非アクティブのtickerがあります: {', '.join(missing)}")
    return selected


def _resolve_to_date(*, to_date: str | None, timezone_name: str) -> str:
    if to_date is not None:
        return normalize_trade_date(to_date)
    return datetime.now(ZoneInfo(timezone_name)).date().isoformat()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    if not args.api_key.strip():
        raise ValueError("J-Quants API key が必要です。--api-key か JQUANTS_API_KEY を設定してください。")

    settings = load_settings()
    to_date = _resolve_to_date(to_date=args.to_date, timezone_name=settings.timezone)
    client = _create_firestore_client(project_id=settings.firestore_project_id)
    watchlist_repo = FirestoreWatchlistRepository(client)
    daily_repo = FirestoreDailyMetricsRepository(client)
    medians_repo = FirestoreMetricMediansRepository(client)
    signal_repo = FirestoreSignalStateRepository(client)
    jquants_client = JQuantsV2Client(api_key=args.api_key.strip())

    target_tickers = _parse_target_tickers(args.tickers)
    watch_items = _select_watchlist_items(watchlist_repo.list_all(), target_tickers=target_tickers)
    LOGGER.info(
        "増分バックフィル開始: to=%s target_tickers=%s dry_run=%s",
        to_date,
        len(watch_items),
        args.dry_run,
    )
    if not watch_items:
        LOGGER.warning("対象tickerが0件です。")

    results: list[IncrementalBackfillResult] = []
    total_generated = 0
    total_upserted = 0
    total_errors = 0
    latest_metrics_by_ticker = {}
    bulk_loader = getattr(daily_repo, "list_latest_by_tickers", None)
    if callable(bulk_loader):
        latest_metrics_by_ticker = bulk_loader([item.ticker for item in watch_items])

    for item in watch_items:
        latest_metric = latest_metrics_by_ticker.get(item.ticker)
        if latest_metric is None and not callable(bulk_loader):
            latest_rows = daily_repo.list_recent(item.ticker, limit=1)
            latest_metric = latest_rows[0] if latest_rows else None
        latest_trade_date = latest_metric.trade_date if latest_metric is not None else None
        from_date = resolve_incremental_from_date(
            latest_trade_date=latest_trade_date,
            to_date=to_date,
            initial_lookback_days=args.initial_lookback_days,
            overlap_days=args.overlap_days,
        )

        try:
            execution = backfill_ticker_from_jquants(
                item=item,
                from_date=from_date,
                to_date=to_date,
                jquants_client=jquants_client,
                daily_metrics_repo=daily_repo,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                refresh_latest_medians_and_signal(
                    item=item,
                    daily_metrics_repo=daily_repo,
                    medians_repo=medians_repo,
                    signal_state_repo=signal_repo,
                    window_1w_days=settings.window_1w_days,
                    window_3m_days=settings.window_3m_days,
                    window_1y_days=settings.window_1y_days,
                )
            total_generated += execution.generated
            total_upserted += execution.upserted
            results.append(
                IncrementalBackfillResult(
                    ticker=item.ticker,
                    from_date=execution.from_date,
                    to_date=execution.to_date,
                    generated=execution.generated,
                    upserted=execution.upserted,
                    errors=0,
                )
            )
            LOGGER.info(
                "増分バックフィル完了: ticker=%s from=%s to=%s generated=%s upserted=%s",
                item.ticker,
                execution.from_date,
                execution.to_date,
                execution.generated,
                execution.upserted,
            )
        except Exception as exc:
            total_errors += 1
            results.append(
                IncrementalBackfillResult(
                    ticker=item.ticker,
                    from_date=from_date,
                    to_date=to_date,
                    generated=0,
                    upserted=0,
                    errors=1,
                )
            )
            LOGGER.exception("増分バックフィル失敗: ticker=%s from=%s to=%s error=%s", item.ticker, from_date, to_date, exc)

    payload = {
        "dry_run": args.dry_run,
        "to_date": to_date,
        "processed_tickers": len(watch_items),
        "generated_rows": total_generated,
        "upserted_rows": total_upserted,
        "errors": total_errors,
        "tickers": [asdict(result) for result in results],
    }
    print(json.dumps(payload, ensure_ascii=False))
    LOGGER.info(
        "増分バックフィル終了: processed_tickers=%s generated_rows=%s upserted_rows=%s errors=%s",
        payload["processed_tickers"],
        payload["generated_rows"],
        payload["upserted_rows"],
        payload["errors"],
    )
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.exception("incremental backfill failed: %s", exc)
        raise SystemExit(1) from exc

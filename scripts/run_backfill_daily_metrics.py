#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os

from kabu_per_bot.backfill import build_daily_metrics_from_jquants_v2
from kabu_per_bot.jquants_v2 import JQuantsV2Client
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_daily_metrics_repository import FirestoreDailyMetricsRepository
from kabu_per_bot.storage.firestore_schema import normalize_ticker
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository
from kabu_per_bot.watchlist import WatchlistItem


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickerBackfillResult:
    ticker: str
    generated: int
    upserted: int
    errors: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill daily_metrics from J-Quants API v2.")
    parser.add_argument("--from-date", required=True, help="Start date (YYYY-MM-DD or YYYYMMDD).")
    parser.add_argument("--to-date", required=True, help="End date (YYYY-MM-DD or YYYYMMDD).")
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


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args()
    if not args.api_key.strip():
        raise ValueError("J-Quants API key が必要です。--api-key か JQUANTS_API_KEY を設定してください。")

    settings = load_settings()
    client = _create_firestore_client(project_id=settings.firestore_project_id)
    watchlist_repo = FirestoreWatchlistRepository(client)
    daily_repo = FirestoreDailyMetricsRepository(client)
    jquants_client = JQuantsV2Client(api_key=args.api_key.strip())

    target_tickers = _parse_target_tickers(args.tickers)
    watch_items = _select_watchlist_items(watchlist_repo.list_all(), target_tickers=target_tickers)
    LOGGER.info(
        "バックフィル開始: from=%s to=%s target_tickers=%s dry_run=%s",
        args.from_date,
        args.to_date,
        len(watch_items),
        args.dry_run,
    )
    if not watch_items:
        LOGGER.warning("対象tickerが0件です。")

    fetched_at = datetime.now(timezone.utc).isoformat()
    per_ticker_results: list[TickerBackfillResult] = []
    total_generated = 0
    total_upserted = 0
    total_errors = 0

    for item in watch_items:
        try:
            bars_daily = jquants_client.get_eq_bars_daily(
                code_or_ticker=item.ticker,
                from_date=args.from_date,
                to_date=args.to_date,
            )
            fin_summary = jquants_client.get_fin_summary(code_or_ticker=item.ticker)
            metrics = build_daily_metrics_from_jquants_v2(
                ticker=item.ticker,
                metric_type=item.metric_type,
                bars_daily_rows=bars_daily,
                fin_summary_rows=fin_summary,
                fetched_at=fetched_at,
            )
            generated = len(metrics)
            upserted = 0
            if not args.dry_run:
                for metric in metrics:
                    daily_repo.upsert(metric)
                    upserted += 1
            total_generated += generated
            total_upserted += upserted
            per_ticker_results.append(
                TickerBackfillResult(
                    ticker=item.ticker,
                    generated=generated,
                    upserted=upserted,
                    errors=0,
                )
            )
            LOGGER.info(
                "バックフィル完了: ticker=%s generated=%s upserted=%s",
                item.ticker,
                generated,
                upserted,
            )
        except Exception as exc:
            total_errors += 1
            per_ticker_results.append(
                TickerBackfillResult(
                    ticker=item.ticker,
                    generated=0,
                    upserted=0,
                    errors=1,
                )
            )
            LOGGER.exception("バックフィル失敗: ticker=%s error=%s", item.ticker, exc)

    payload = {
        "dry_run": args.dry_run,
        "from_date": args.from_date,
        "to_date": args.to_date,
        "processed_tickers": len(watch_items),
        "generated_rows": total_generated,
        "upserted_rows": total_upserted,
        "errors": total_errors,
        "tickers": [asdict(result) for result in per_ticker_results],
    }
    print(json.dumps(payload, ensure_ascii=False))
    LOGGER.info(
        "バックフィル終了: processed_tickers=%s generated_rows=%s upserted_rows=%s errors=%s",
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
        LOGGER.exception("backfill daily metrics failed: %s", exc)
        raise SystemExit(1) from exc


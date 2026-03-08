#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
import logging
import os
from zoneinfo import ZoneInfo

from kabu_per_bot.jquants_v2 import JQuantsV2Client
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_price_bars_daily_repository import FirestorePriceBarsDailyRepository
from kabu_per_bot.storage.firestore_schema import normalize_ticker, normalize_trade_date
from kabu_per_bot.storage.firestore_technical_sync_state_repository import FirestoreTechnicalSyncStateRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository
from kabu_per_bot.technical_sync import (
    DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS,
    DEFAULT_TECHNICAL_OVERLAP_DAYS,
    resolve_technical_sync_from_date,
    sync_ticker_price_bars,
)
from kabu_per_bot.watchlist import WatchlistItem


LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run technical price-bar sync from J-Quants LITE.")
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
        default=DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS,
        help=f"Lookback days when ticker has no sync history (default: {DEFAULT_TECHNICAL_INITIAL_LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--overlap-days",
        type=int,
        default=DEFAULT_TECHNICAL_OVERLAP_DAYS,
        help=f"Overlap days from latest fetched trade date (default: {DEFAULT_TECHNICAL_OVERLAP_DAYS}).",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Ignore latest_fetched_trade_date and refetch from the initial lookback window.",
    )
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
    price_bars_repo = FirestorePriceBarsDailyRepository(client)
    sync_state_repo = FirestoreTechnicalSyncStateRepository(client)
    jquants_client = JQuantsV2Client(api_key=args.api_key.strip())

    target_tickers = _parse_target_tickers(args.tickers)
    watch_items = _select_watchlist_items(watchlist_repo.list_all(), target_tickers=target_tickers)
    LOGGER.info(
        "技術価格バー同期開始: to=%s target_tickers=%s full_refresh=%s",
        to_date,
        len(watch_items),
        args.full_refresh,
    )
    if not watch_items:
        LOGGER.warning("対象tickerが0件です。")

    results = []
    total_fetched = 0
    total_upserted = 0
    total_errors = 0

    for item in watch_items:
        state = sync_state_repo.get(item.ticker)
        from_date = resolve_technical_sync_from_date(
            latest_fetched_trade_date=(state.latest_fetched_trade_date if state is not None else None),
            to_date=to_date,
            initial_lookback_days=args.initial_lookback_days,
            overlap_days=args.overlap_days,
            full_refresh=args.full_refresh,
        )
        try:
            result = sync_ticker_price_bars(
                item=item,
                from_date=from_date,
                to_date=to_date,
                jquants_client=jquants_client,
                price_bars_repo=price_bars_repo,
                sync_state_repo=sync_state_repo,
                full_refresh=args.full_refresh,
            )
            total_fetched += result.fetched_rows
            total_upserted += result.upserted_rows
            results.append(asdict(result))
            LOGGER.info(
                "技術価格バー同期完了: ticker=%s from=%s to=%s fetched=%s upserted=%s",
                result.ticker,
                result.from_date,
                result.to_date,
                result.fetched_rows,
                result.upserted_rows,
            )
        except Exception as exc:
            total_errors += 1
            results.append(
                {
                    "ticker": item.ticker,
                    "from_date": from_date,
                    "to_date": to_date,
                    "fetched_rows": 0,
                    "upserted_rows": 0,
                    "latest_fetched_trade_date": state.latest_fetched_trade_date if state is not None else None,
                    "full_refresh": args.full_refresh,
                    "error": str(exc),
                }
            )
            LOGGER.exception("技術価格バー同期失敗: ticker=%s from=%s to=%s error=%s", item.ticker, from_date, to_date, exc)

    payload = {
        "to_date": to_date,
        "full_refresh": args.full_refresh,
        "processed_tickers": len(watch_items),
        "fetched_rows": total_fetched,
        "upserted_rows": total_upserted,
        "errors": total_errors,
        "tickers": results,
    }
    print(json.dumps(payload, ensure_ascii=False))
    LOGGER.info(
        "技術価格バー同期終了: processed_tickers=%s fetched_rows=%s upserted_rows=%s errors=%s",
        payload["processed_tickers"],
        payload["fetched_rows"],
        payload["upserted_rows"],
        payload["errors"],
    )
    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        LOGGER.exception("technical price sync failed: %s", exc)
        raise SystemExit(1) from exc

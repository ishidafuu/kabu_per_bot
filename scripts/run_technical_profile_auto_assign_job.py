#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os

from kabu_per_bot.market_data import create_default_market_data_source
from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_technical_indicators_daily_repository import FirestoreTechnicalIndicatorsDailyRepository
from kabu_per_bot.storage.firestore_technical_profiles_repository import FirestoreTechnicalProfilesRepository
from kabu_per_bot.storage.firestore_watchlist_repository import FirestoreWatchlistRepository
from kabu_per_bot.technical_profile_auto_assign import auto_assign_technical_profiles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run technical profile auto assignment.")
    parser.add_argument(
        "--allow-manual-fallback",
        action="store_true",
        help="manual_only profile の fallback_rule を評価します。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    client = _create_firestore_client(settings.firestore_project_id)
    watchlist_repo = FirestoreWatchlistRepository(client)
    indicators_repo = FirestoreTechnicalIndicatorsDailyRepository(client)
    technical_profiles_repo = FirestoreTechnicalProfilesRepository(client)
    market_data_source = create_default_market_data_source(jquants_api_key=os.environ.get("JQUANTS_API_KEY", "").strip())
    result = auto_assign_technical_profiles(
        watchlist_items=watchlist_repo.list_all(),
        watchlist_repo=watchlist_repo,
        technical_indicators_repo=indicators_repo,
        technical_profiles_repo=technical_profiles_repo,
        market_data_source=market_data_source,
        allow_manual_fallback=args.allow_manual_fallback,
    )
    print(json.dumps({
        "processed_tickers": result.processed_tickers,
        "updated_tickers": result.updated_tickers,
        "skipped_manual_override": result.skipped_manual_override,
        "matched_tickers": result.matched_tickers,
        "assignments": list(result.assignments),
    }, ensure_ascii=False, indent=2))


def _create_firestore_client(project_id: str | None):
    try:
        from google.cloud import firestore
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise RuntimeError(
            "google-cloud-firestore が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc
    return firestore.Client(project=project_id or None)


if __name__ == "__main__":
    main()

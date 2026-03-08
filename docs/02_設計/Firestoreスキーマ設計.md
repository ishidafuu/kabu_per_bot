# Firestoreスキーマ設計（Issue 02）

このドキュメントは、現行実装のFirestore構成と、合意済みの拡張予定をまとめた設計書である。  
未実装の項目は `拡張予定` と明記して区別する。

## 1. コレクション一覧

1. `watchlist`
2. `watchlist_history`
3. `daily_metrics`
4. `metric_medians`
5. `signal_state`
6. `earnings_calendar`
7. `notification_log`
8. `job_run`
9. `intel_seen`
10. `global_settings`

## 2. 一意制約（ドキュメントIDで担保）

FirestoreはRDBの一意制約を持たないため、ドキュメントIDを合成キーにする。

1. `watchlist`
   - doc id: `{ticker}`（例: `3901:TSE`）
   - 主要フィールド: `ticker`, `name`, `metric_type`, `notify_channel`, `notify_timing`, `always_notify_enabled`, `ai_enabled`（互換用・常時true運用）, `is_active`, `ir_urls`, `x_official_account`, `x_executive_accounts`
2. `daily_metrics`
   - doc id: `{ticker}|{trade_date}`
3. `metric_medians`
   - doc id: `{ticker}|{trade_date}`
4. `signal_state`
   - doc id: `{ticker}|{trade_date}`
5. `earnings_calendar`
   - doc id: `{ticker}|{earnings_date}|{quarter_or_NA}`
   - 必須フィールド: `ticker`, `earnings_date`
   - 欠損許容フィールド: `earnings_time`, `quarter`, `source`, `fetched_at`
6. `notification_log`
   - doc id: `{entry_id}`
   - 必須フィールド: `id`, `ticker`, `category`, `condition_key`, `sent_at`, `channel`, `is_strong`
   - 任意フィールド: `payload_hash`, `body`
7. `job_run`
   - doc id: `{job_name}|{hash}`
   - 必須フィールド: `job_name`, `started_at`, `finished_at`, `status`, `error_count`, `failed`
   - `status` は `SUCCESS` / `FAILED`
8. `intel_seen`
   - doc id: `{fingerprint}`
   - 主要フィールド: `id`, `ticker`, `kind`（`IR`/`SNS`）, `title`, `url`, `published_at`, `source_label`, `seen_at`
9. `global_settings`
   - doc id: `runtime`
   - 主なフィールド:
     - `cooldown_hours`
     - `intel_notification_max_age_days`
     - `immediate_schedule_enabled`
     - `immediate_schedule_timezone`
     - `immediate_open_window_start`
     - `immediate_open_window_end`
     - `immediate_open_window_interval_min`
     - `immediate_close_window_start`
     - `immediate_close_window_end`
     - `immediate_close_window_interval_min`
     - `grok_sns_enabled`
     - `grok_sns_scheduled_time`
     - `grok_sns_per_ticker_cooldown_hours`
     - `grok_sns_prompt_template`
     - `updated_at`
     - `updated_by`

## 3. インデックス

`/Users/ishidafuu/Documents/repository/kabu_per_bot/firestore.indexes.json` で定義する。

- `watchlist_history`: `ticker asc`, `acted_at desc`
- `daily_metrics`: `ticker asc`, `trade_date desc`
- `metric_medians`: `ticker asc`, `trade_date desc`
- `signal_state`: `ticker asc`, `trade_date desc`
- `earnings_calendar`: `earnings_date asc`, `ticker asc`
- `notification_log`: `ticker asc`, `sent_at desc`
- `notification_log`: `category asc`, `sent_at desc`

## 4. マイグレーション

初期マイグレーションID: `0001_initial`

- 実行スクリプト:
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/scripts/migrate_firestore_v0001.py`
- 実行結果:
  - `_meta/schema` にスキーマバージョン保存
  - `_meta/schema/migrations/0001_initial` に適用記録保存
  - `_meta/schema/collections/{collection}` にコレクション登録
- 並行実行対策:
  - `_meta/schema/migrations/0001_initial_lock` をロックとして使用し、同時適用を抑制する
  - 適用記録（`0001_initial`）は最後に保存する

この仕組みにより、同じマイグレーションの二重適用を防止する。

## 5. 拡張予定: 価格・需給テクニカル指標

本章は未実装の拡張予定であり、価格・需給テクニカル指標の保存先を `daily_metrics` から分離する前提で定義する。  
指標そのものの計算式・例外処理は [価格・需給テクニカル指標仕様_ドラフト.md](/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/01_要件定義/価格・需給テクニカル指標仕様_ドラフト.md) を正とする。

### 5.1 追加コレクション一覧

1. `price_bars_daily`
2. `technical_indicators_daily`
3. `technical_sync_state`

### 5.2 一意制約（ドキュメントIDで担保）

1. `price_bars_daily`
   - doc id: `{ticker}|{trade_date}`
   - 必須フィールド:
     - `ticker`
     - `trade_date`
     - `code`
     - `date`
     - `open`
     - `high`
     - `low`
     - `close`
     - `volume`
     - `turnover_value`
     - `adj_open`
     - `adj_high`
     - `adj_low`
     - `adj_close`
     - `adj_volume`
     - `source`
     - `fetched_at`
   - 任意フィールド:
     - `data_source_plan`
     - `raw_payload_version`
     - `updated_at`
   - 用途:
     - J-Quants日足バーの正本保存先
     - テクニカル再計算時の唯一の入力データ

2. `technical_indicators_daily`
   - doc id: `{ticker}|{trade_date}`
   - 必須フィールド:
     - `ticker`
     - `trade_date`
     - `schema_version`
     - `calculated_at`
   - 任意フィールド:
     - `close_vs_ma5`
     - `close_vs_ma25`
     - `close_vs_ma75`
     - `close_vs_ma200`
     - `drawdown_from_52w_high`
     - `days_from_52w_high`
     - `turnover_ratio`
     - `turnover_stability_flag`
     - `volatility_20d`
     - `atr_14`
     - `atr_pct_14`
     - その他、価格・需給テクニカル指標仕様に定義した日次項目一式
   - 用途:
     - 日次算出済みテクニカル指標の参照先
     - Web表示、将来のスクリーニング、判定ロジックの入力

3. `technical_sync_state`
   - doc id: `{ticker}`
   - 必須フィールド:
     - `ticker`
     - `latest_fetched_trade_date`
     - `latest_calculated_trade_date`
     - `last_run_at`
     - `last_status`
   - 任意フィールド:
     - `last_fetch_from`
     - `last_fetch_to`
     - `last_error`
     - `last_full_refresh_at`
     - `schema_version`
   - 用途:
     - 差分取得の開始位置管理
     - 再計算の進捗管理
     - 障害時の再開位置管理

### 5.3 保存方針

1. `price_bars_daily` は `raw input` の正本として扱う。
2. `technical_indicators_daily` は `derived data` として扱い、いつでも再計算できる前提にする。
3. `daily_metrics` は既存の `PER / PSR` 用の正本とし、価格・需給テクニカル指標は混在させない。
4. 差分更新は `technical_sync_state` を基準に進める。
5. 失敗時は `technical_sync_state` を進めず、次回実行で再試行できるようにする。

### 5.4 想定クエリ

1. 銘柄別の最新バー取得
   - `price_bars_daily` を `ticker asc, trade_date desc` で取得
2. 銘柄別の最新指標取得
   - `technical_indicators_daily` を `ticker asc, trade_date desc` で取得
3. 銘柄別の再計算用履歴取得
   - `price_bars_daily` を `ticker asc, trade_date desc` で `limit 520` 前後取得
4. 同期待ち銘柄の状態確認
   - `technical_sync_state` を `ticker` 単位で取得

### 5.5 追加インデックス案

`firestore.indexes.json` への追加候補は以下とする。

- `price_bars_daily`: `ticker asc`, `trade_date desc`
- `technical_indicators_daily`: `ticker asc`, `trade_date desc`

`technical_sync_state` は doc id 直接参照を基本とするため、追加の複合インデックスは不要とする。

### 5.6 想定マイグレーション

実装時は新規マイグレーションとして、以下を想定する。

- 想定マイグレーションID: `0002_technical_indicators`
- 想定作業:
  - `_meta/schema/collections/price_bars_daily` を登録
  - `_meta/schema/collections/technical_indicators_daily` を登録
  - `_meta/schema/collections/technical_sync_state` を登録
  - `firestore.indexes.json` に複合インデックスを追加
  - スキーマバージョンを `2` に更新

### 5.7 運用メモ

1. 日次ジョブは `watchlist.is_active=true` の銘柄だけを同期対象にする。
2. API再取得は、直近の訂正や調整後価格更新を吸収するため、前回取得日からの完全差分ではなく `30暦日` のオーバーラップを持たせる。
3. 再計算は `直近260営業日` の再書込を基本とし、`200日MA` と `52週高値` を安全に更新できるようにする。
4. 週1回または手動で全件再同期ジョブを持ち、分割・併合などで広範囲に再調整がかかった場合を吸収する。

### 5.8 `firestore.indexes.json` 追記案

実装時は、既存の `indexes` 配列へ以下を追加する想定とする。

```json
{
  "collectionGroup": "price_bars_daily",
  "queryScope": "COLLECTION",
  "fields": [
    { "fieldPath": "ticker", "order": "ASCENDING" },
    { "fieldPath": "trade_date", "order": "DESCENDING" }
  ]
},
{
  "collectionGroup": "technical_indicators_daily",
  "queryScope": "COLLECTION",
  "fields": [
    { "fieldPath": "ticker", "order": "ASCENDING" },
    { "fieldPath": "trade_date", "order": "DESCENDING" }
  ]
}
```

補足:

1. `technical_sync_state` は doc id を `ticker` にするため、複合インデックス追加は不要とする。
2. 現時点では `where + orderBy` の追加要件を置かないため、最小構成は上記2本とする。
3. Web側で将来 `schema_version` や `last_status` 条件検索を入れる場合は、その時点で追加する。

### 5.9 `0002_technical_indicators` マイグレーション雛形

既存の `v0001` は `src/kabu_per_bot/storage/firestore_migration.py` と `scripts/migrate_firestore_v0001.py` の2層構成である。  
`v0002` も同じ方針で、`別モジュール + 別スクリプト` で追加する。

想定ファイル:

1. `src/kabu_per_bot/storage/firestore_migration_v0002.py`
2. `scripts/migrate_firestore_v0002_technical_indicators.py`

#### 5.9.1 `src/kabu_per_bot/storage/firestore_migration_v0002.py` 雛形

```python
from __future__ import annotations

from kabu_per_bot.storage.firestore_migration import (
    COLLECTION_REGISTRY_PATH,
    META_SCHEMA_DOC_PATH,
    MIGRATIONS_COLLECTION_PATH,
    DocumentStore,
    MigrationOperation,
)


SCHEMA_VERSION_V0002 = 2
MIGRATION_ID_V0002 = "0002_technical_indicators"
MIGRATION_DOC_PATH_V0002 = f"{MIGRATIONS_COLLECTION_PATH}/{MIGRATION_ID_V0002}"
MIGRATION_LOCK_DOC_PATH_V0002 = f"{MIGRATIONS_COLLECTION_PATH}/{MIGRATION_ID_V0002}_lock"

TECHNICAL_COLLECTIONS = (
    "price_bars_daily",
    "technical_indicators_daily",
    "technical_sync_state",
)


def build_v0002_migration_operations(applied_at: str) -> list[MigrationOperation]:
    ops: list[MigrationOperation] = [
        MigrationOperation(
            path=META_SCHEMA_DOC_PATH,
            data={
                "current_schema_version": SCHEMA_VERSION_V0002,
                "updated_at": applied_at,
            },
            merge=True,
        ),
    ]
    for collection_name in TECHNICAL_COLLECTIONS:
        ops.append(
            MigrationOperation(
                path=f"{COLLECTION_REGISTRY_PATH}/{collection_name}",
                data={
                    "name": collection_name,
                    "created_by_migration": MIGRATION_ID_V0002,
                    "schema_version": SCHEMA_VERSION_V0002,
                    "created_at": applied_at,
                },
            )
        )
    ops.append(
        MigrationOperation(
            path=MIGRATION_DOC_PATH_V0002,
            data={
                "id": MIGRATION_ID_V0002,
                "schema_version": SCHEMA_VERSION_V0002,
                "applied_at": applied_at,
                "status": "completed",
            },
        )
    )
    return ops


def apply_v0002_migration(store: DocumentStore, *, applied_at: str) -> bool:
    existing = store.get_document(MIGRATION_DOC_PATH_V0002)
    if existing is not None:
        return False

    lock_acquired = store.create_document(
        MIGRATION_LOCK_DOC_PATH_V0002,
        {
            "id": MIGRATION_ID_V0002,
            "status": "running",
            "started_at": applied_at,
        },
    )
    if not lock_acquired:
        return False

    try:
        if store.get_document(MIGRATION_DOC_PATH_V0002) is not None:
            return False
        for op in build_v0002_migration_operations(applied_at):
            store.set_document(op.path, op.data, merge=op.merge)
        return True
    finally:
        store.delete_document(MIGRATION_LOCK_DOC_PATH_V0002)
```

#### 5.9.2 `scripts/migrate_firestore_v0002_technical_indicators.py` 雛形

```python
#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import sys

from kabu_per_bot.settings import load_settings
from kabu_per_bot.storage.firestore_migration_v0002 import apply_v0002_migration
from kabu_per_bot.storage.firestore_store import FirestoreDocumentStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply Firestore schema migration v0002 for technical indicators."
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="Firestore project id. If omitted, FIRESTORE_PROJECT_ID from settings is used.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    project_id = (args.project_id or settings.firestore_project_id).strip()
    if not project_id:
        print(
            "Firestore project id is required. Set --project-id or FIRESTORE_PROJECT_ID.",
            file=sys.stderr,
        )
        return 2

    try:
        from google.cloud import firestore
    except ModuleNotFoundError:
        print("google-cloud-firestore is not installed. Install with: pip install '.[gcp]'", file=sys.stderr)
        return 1

    client = firestore.Client(project=project_id)
    store = FirestoreDocumentStore(client)
    applied = apply_v0002_migration(
        store,
        applied_at=datetime.now(timezone.utc).isoformat(),
    )
    if applied:
        print("Applied Firestore migration 0002_technical_indicators")
    else:
        print("Firestore migration 0002_technical_indicators was already applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### 5.10 実装時の差分メモ

1. `src/kabu_per_bot/storage/firestore_schema.py` に以下の定数追加が必要になる。
   - `COLLECTION_PRICE_BARS_DAILY`
   - `COLLECTION_TECHNICAL_INDICATORS_DAILY`
   - `COLLECTION_TECHNICAL_SYNC_STATE`
2. `ALL_COLLECTIONS` は、実装着手時に上記3コレクションを追加する。
3. `SCHEMA_VERSION` と `MIGRATION_ID` は現状 `v0001` 専用の置き方になっているため、`v0002` 実装時は `firestore_migration_v0002.py` 側でローカル定数を持つ。
4. Firestoreはコレクションを事前作成しないため、マイグレーションの本質は `_meta/schema` 更新とコレクション登録である。
5. `firestore.indexes.json` の反映は、マイグレーション適用と別手順でデプロイされる点に注意する。

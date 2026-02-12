# Firestoreスキーマ設計（Issue 02）

## 1. コレクション一覧

1. `watchlist`
2. `watchlist_history`
3. `daily_metrics`
4. `metric_medians`
5. `signal_state`
6. `earnings_calendar`
7. `notification_log`

## 2. 一意制約（ドキュメントIDで担保）

FirestoreはRDBの一意制約を持たないため、ドキュメントIDを合成キーにする。

1. `watchlist`
   - doc id: `{ticker}`（例: `3901:TSE`）
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

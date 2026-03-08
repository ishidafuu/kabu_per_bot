# 価格・需給テクニカル指標 実装Issue分解（ドラフト）

最終更新: 2026-03-08（JST）

## 1. 目的

- `J-Quants Light` を前提に、ウォッチリスト登録銘柄の日足テクニカル指標を日次保存し、条件成立時にDiscord通知する機能をフル実装する。
- 実装を `1 Issue = 1目的` に分割し、依存関係と受け入れ基準を先に固定する。
- 既存の `PER / PSR` 通知運用を壊さず、別系統の価格・需給テクニカル基盤として追加する。

## 2. 前提

- 対象データソースは `J-Quants Light` の `日足OHLCV + 調整後OHLCV` とする。
- 対象は `watchlist.is_active=true` の銘柄のみとする。
- 通知は `日足確定後のデイリー通知` を前提とし、場中リアルタイム通知は対象外とする。
- `時価総額` と `配当落ちイベント補正` は、現時点の `J-Quants Light` 単独では前提を置かないため、本分解の対象外とする。
- 指標定義の正本は [価格・需給テクニカル指標仕様_ドラフト.md](/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/01_要件定義/価格・需給テクニカル指標仕様_ドラフト.md) とする。
- 保存設計の正本は [Firestoreスキーマ設計.md](/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/02_設計/Firestoreスキーマ設計.md) の拡張予定章とする。

## 3. 完成イメージ

1. `watchlist` の active 銘柄を対象に、J-Quants から日足バーを差分取得する。
2. `price_bars_daily` に保存する。
3. 保存済み履歴からテクニカル指標を再計算し、`technical_indicators_daily` に保存する。
4. 銘柄ごとの `technical_alert_rules` を評価する。
5. 発火時は Discord 通知し、通知履歴を `notification_log` に残す。
6. 進捗管理と再実行管理は `technical_sync_state` と `/ops` から行えるようにする。

## 4. Issue依存マップ

1. Issue 01: Firestore拡張とマイグレーション
2. Issue 02: Repository / ドメインモデル追加
3. Issue 03: J-Quants日足同期ジョブ
4. Issue 04: テクニカル指標計算・保存
5. Issue 05: 技術アラートルール管理API
6. Issue 06: 技術アラート評価とDiscord通知
7. Issue 07: `/ops` / Cloud Run Job 組み込み
8. Issue 08: Web管理画面対応
9. Issue 09: テスト・運用手順・正本更新

依存関係は以下の通りとする。

- Issue 02 は Issue 01 に依存
- Issue 03 は Issue 02 に依存
- Issue 04 は Issue 03 に依存
- Issue 05 は Issue 02 に依存
- Issue 06 は Issue 04 と Issue 05 に依存
- Issue 07 は Issue 03 と Issue 06 に依存
- Issue 08 は Issue 05 と Issue 06 に依存
- Issue 09 は全Issueに依存

## 5. Issue一覧

### Issue 01: Firestore拡張とマイグレーション

- 概要
  - テクニカル指標用のコレクション、インデックス、スキーマ登録マイグレーションを追加する。
- 背景/目的
  - 既存の `daily_metrics` は `PER / PSR` 用の正本であり、価格テクニカルを混在させると責務が崩れる。
  - 差分同期と再計算を安全に回すには、バー保存先と指標保存先を分離する必要がある。
- スコープ
  - `firestore_schema.py` へのコレクション定数追加
  - `firestore.indexes.json` 追記
  - `0002_technical_indicators` マイグレーション実装
  - `_meta/schema` のコレクション登録
- 受け入れ基準
  - `price_bars_daily`, `technical_indicators_daily`, `technical_sync_state`, `technical_alert_rules`, `technical_alert_state` の定数が定義されている
  - `firestore.indexes.json` に `price_bars_daily` と `technical_indicators_daily` の複合インデックスが追加されている
  - `scripts/migrate_firestore_v0002_technical_indicators.py` でマイグレーションを一度だけ適用できる
  - 2回目実行時は `already applied` 扱いになる
  - `_meta/schema/collections/*` に新コレクションが登録される
- 依存Issue
  - なし

### Issue 02: Repository / ドメインモデル追加

- 概要
  - テクニカル基盤用のドメインモデルと Firestore repository を追加する。
- 背景/目的
  - バー保存、指標保存、ルール保存、状態保存を分けて扱わないと、ジョブ実装とAPI実装の責務分離ができない。
- スコープ
  - `PriceBarDaily`
  - `TechnicalIndicatorsDaily`
  - `TechnicalAlertRule`
  - `TechnicalAlertState`
  - `TechnicalSyncState`
  - 上記の Firestore repository 実装
- 受け入れ基準
  - 各モデルに `from_document()` と `to_document()` がある
  - doc id 規則が `ticker|trade_date` または `ticker` に統一されている
  - repository に最低限 `get / upsert / list_recent` が揃っている
  - Firestore を使わない単体テストで round-trip が通る
- 依存Issue
  - Issue 01

### Issue 03: J-Quants日足同期ジョブ

- 概要
  - active watchlist 銘柄を対象に、J-Quants から日足バーを差分同期して `price_bars_daily` に保存する。
- 背景/目的
  - テクニカル指標は保存済みの日足履歴を正本として計算する必要がある。
  - APIを毎日全件取得すると無駄が大きいため、差分同期が必要である。
- スコープ
  - J-Quants 日足取得ロジック
  - 初回一括同期
  - `30暦日` オーバーラップ差分同期
  - `technical_sync_state` 更新
  - 週1回または手動の全件再同期
- 受け入れ基準
  - 初回実行で対象銘柄の取得可能期間が `price_bars_daily` に保存される
  - 2回目以降は `latest_fetched_trade_date - 30日` から再取得される
  - 保存失敗時は `technical_sync_state.latest_fetched_trade_date` が進まない
  - 全件再同期用のCLIまたはジョブ引数が用意されている
  - 取得件数と失敗件数がログで追跡できる
- 依存Issue
  - Issue 02

### Issue 04: テクニカル指標計算・保存

- 概要
  - 合意済みの価格・需給テクニカル指標を保存済みバーから一括計算し、`technical_indicators_daily` に保存する。
- 背景/目的
  - 通知判定の前に、日次で再利用可能な指標ストアを作る必要がある。
  - 指標計算を通知処理から切り離すことで、再計算・検証・UI表示が容易になる。
- スコープ
  - `technical_indicators.py` 新設
  - A〜I のうち J-Quants 起点で実装可能な全指標の計算
  - `schema_version` 付き保存
  - `直近520営業日読込 / 直近260営業日再書込`
- 受け入れ基準
  - 指標定義ドラフトにある対象項目が `technical_indicators_daily` に保存される
  - 履歴不足時の `null / false` 挙動が仕様書どおり
  - `high == low` 時の例外処理が仕様書どおり
  - `200日MA`, `52週高値`, `ATR`, `volatility_20d` を含む長期項目が計算できる
  - 主要指標の単体テストが追加される
- 依存Issue
  - Issue 03

### Issue 05: 技術アラートルール管理API

- 概要
  - 銘柄ごとの技術アラートルールを保存・更新・参照するAPIとモデルを追加する。
- 背景/目的
  - 通知条件は銘柄ごとに異なるため、ルールをコード固定せず保存可能にする必要がある。
  - watchlist 本体へ埋め込まず別コレクションにすることで、ルール数増加に耐えられる構成にする。
- スコープ
  - `technical_alert_rules` repository
  - ドメインルール定義
  - API schema 追加
  - watchlist 詳細APIへのルール読込
  - ルール CRUD API
- 受け入れ基準
  - 1銘柄に複数ルールを設定できる
  - ルール型として `IS_TRUE`, `IS_FALSE`, `GTE`, `LTE`, `BETWEEN`, `OUTSIDE` を扱える
  - `field_key` はテクニカル指標仕様に定義済みのキーに限定される
  - API経由で作成・更新・無効化・一覧取得ができる
  - 不正な `field_key` や演算子はバリデーションで弾かれる
- 依存Issue
  - Issue 02

### Issue 06: 技術アラート評価とDiscord通知

- 概要
  - 保存済み指標とルールを評価し、条件成立時にDiscord通知するパイプラインを追加する。
- 背景/目的
  - この機能の主目的は「条件成立時のアラート通知」であり、ルール評価と通知抑止の安定化が中心になる。
  - 既存のクールダウンと通知ログ基盤を流用することで、運用の一貫性を保つ。
- スコープ
  - `technical_alerts.py` 新設
  - `technical_pipeline.py` 新設
  - `technical_alert_state` 更新
  - Discord通知 formatter 追加
  - 既存 `notification_log` 連携
- 受け入れ基準
  - イベント型ルールは `当日true` で発火する
  - 数値型ルールは `前日未達 -> 当日達成` のクロス判定で発火する
  - `condition_key=TECH:{rule_id}` で通知ログに保存される
  - クールダウンは既存ロジックに従って抑止される
  - 通知本文に `銘柄`, `ルール名`, `現在値`, `しきい値`, `補助情報` が含まれる
  - `technical_alert_state` に前回判定結果と前回発火日時が残る
- 依存Issue
  - Issue 04
  - Issue 05

### Issue 07: `/ops` / Cloud Run Job 組み込み

- 概要
  - テクニカル同期・計算・通知ジョブを `/ops` と Cloud Run Job から実行できるようにする。
- 背景/目的
  - 障害時の再実行、手動同期、全件再同期を既存運用と同じ導線で扱える必要がある。
- スコープ
  - `run_technical_daily_job.py`
  - `run_technical_full_refresh_job.py` または同等の全件再同期経路
  - `admin_ops.py` へのジョブ追加
  - 実行結果の `job_run` 反映
- 受け入れ基準
  - `/ops` から日次技術ジョブを起動できる
  - `/ops` から全件再同期ジョブを起動できる
  - 実行履歴が既存ジョブと同様に参照できる
  - 失敗時にエラー内容が追跡できる
  - `stdout preview` または dry-run 相当の確認手段がある
- 依存Issue
  - Issue 03
  - Issue 06

### Issue 08: Web管理画面対応

- 概要
  - watchlist 詳細画面からテクニカル指標の確認とアラートルール設定ができるようにする。
- 背景/目的
  - 運用者がコードやFirestoreを直接触らずに設定・確認できないと、実運用で破綻する。
- スコープ
  - watchlist 詳細に `テクニカル` セクションまたはタブ追加
  - 最新テクニカル値表示
  - アラートルール一覧
  - アラートルール作成・編集・無効化 UI
  - 直近発火履歴表示
- 受け入れ基準
  - watchlist 詳細で最新指標が表示される
  - UIからルールを追加・編集・無効化できる
  - ルール保存後にAPIと表示が一致する
  - 発火履歴が確認できる
  - `npm run lint` と E2E が通る
- 依存Issue
  - Issue 05
  - Issue 06

### Issue 09: テスト・運用手順・正本更新

- 概要
  - フル実装後のテスト整備、運用ドキュメント更新、正本反映を行う。
- 背景/目的
  - テクニカル通知は誤報や未報の影響が大きいため、計算・通知・運用手順を文書とテストで固定する必要がある。
- スコープ
  - 単体テスト
  - 結合テスト
  - Web E2E
  - 運用手順書更新
  - 正本ドキュメント更新
  - ロールアウト手順の明文化
- 受け入れ基準
  - `PYTHONPATH=src python -m unittest discover -s tests` が通る
  - `web/npm run lint` が通る
  - `web/npm run test:e2e` と `npm run test:e2e:api` の対象差分が通る
  - `docs/` の関連正本が更新されている
  - `/ops` を使った日常運用手順が文書化されている
  - 障害時の再同期手順が文書化されている
- 依存Issue
  - Issue 01
  - Issue 02
  - Issue 03
  - Issue 04
  - Issue 05
  - Issue 06
  - Issue 07
  - Issue 08

## 6. 実装順の推奨

1. Issue 01
2. Issue 02
3. Issue 03
4. Issue 04
5. Issue 05
6. Issue 06
7. Issue 07
8. Issue 08
9. Issue 09

## 7. 非スコープ

- 場中リアルタイム通知
- `時価総額` を使った判定
- `配当落ちイベント補正`
- J-Quants 以外の恒久的な新規データソース追加

## 8. 補足

- フル実装前提ではあるが、実装順は依存順に分ける。
- これはMVP切り捨てではなく、最終形に向けて安全に積み上げるためのIssue分割である。
- 実装着手後に仕様変更が出た場合は、本書の受け入れ基準を先に更新してから実装する。

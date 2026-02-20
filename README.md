# kabu_per_bot
株式監視BOT

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e ".[gcp]"
```

## 起動確認

```bash
python -m kabu_per_bot
```

### Web API（FastAPI）起動

```bash
uvicorn kabu_per_bot.api.app:app --reload
```

- OpenAPI: `http://127.0.0.1:8000/docs`
- ヘルスチェック: `GET /api/v1/healthz` -> `{"status":"ok"}`
- ウォッチリストAPI: `GET/POST/PATCH/DELETE /api/v1/watchlist`
- 認証: `Authorization: Bearer <Firebase IDトークン>`

### 管理運用ページ（`/ops`）

運用操作は `ダッシュボード` から分離し、`/ops` に集約しています（管理者のみ）。

- 寄り付き帯ジョブ実行（`kabu-immediate-open`）
- 引け帯ジョブ実行（`kabu-immediate-close`）
- 日次ジョブ実行（`kabu-daily`）
- 21:05ジョブ実行（`kabu-daily-at21`）
- 今週決算ジョブ実行（`kabu-earnings-weekly`）
- 明日決算ジョブ実行（`kabu-earnings-tomorrow`）
- Discord疎通テスト送信
- Cloud Run 実行履歴表示
- 日次系ジョブのスキップ理由集計（Cloud Logging解析）

補足:
- バックフィルは誤操作防止のためWeb画面からは実行しません。必要時は `scripts/run_backfill_daily_metrics.py` または Cloud Run Job を使用してください。
- `kabu-intelligence` / `kabu-grok` は定期実行前提のため、`/ops` の手動実行メニューには表示しません。

必要な環境変数（API側）:

- `API_ADMIN_UIDS`: 管理者UID（`,`区切り）。または Firebase カスタムクレーム `admin=true`
- `OPS_GCP_PROJECT_ID`: Cloud Run Job 実行先プロジェクト（未指定時は `FIRESTORE_PROJECT_ID`）
- `OPS_GCP_REGION`: Cloud Run リージョン（既定: `asia-northeast1`）
- `OPS_IMMEDIATE_OPEN_JOB_NAME`（既定: `kabu-immediate-open`）
- `OPS_IMMEDIATE_CLOSE_JOB_NAME`（既定: `kabu-immediate-close`）
- `OPS_DAILY_JOB_NAME`（既定: `kabu-daily`）
- `OPS_DAILY_AT21_JOB_NAME`（既定: `kabu-daily-at21`）
- `OPS_EARNINGS_WEEKLY_JOB_NAME`（既定: `kabu-earnings-weekly`）
- `OPS_EARNINGS_TOMORROW_JOB_NAME`（既定: `kabu-earnings-tomorrow`）
- `INTEL_NOTIFICATION_MAX_AGE_DAYS`（IR/SNS通知対象期間の環境変数デフォルト。既定: `30`）
- `DISCORD_WEBHOOK_URL`（全ジョブ共通の通知先。未分割時に使用）
- `DISCORD_WEBHOOK_URL_DAILY`（日次/IMMEDIATEジョブ専用。未設定時は `DISCORD_WEBHOOK_URL` を使用）
- `DISCORD_WEBHOOK_URL_EARNINGS`（決算ジョブ専用。未設定時は `DISCORD_WEBHOOK_URL` を使用）
- `DISCORD_WEBHOOK_URL_INTELLIGENCE`（IR/SNS共通fallback。未設定時は `DISCORD_WEBHOOK_URL` を使用）
- `DISCORD_WEBHOOK_URL_INTELLIGENCE_IR`（IR通知専用。未設定時は `DISCORD_WEBHOOK_URL_INTELLIGENCE` を使用）
- `DISCORD_WEBHOOK_URL_INTELLIGENCE_SNS`（SNS/AI通知専用。未設定時は `DISCORD_WEBHOOK_URL_INTELLIGENCE` を使用）
- `GROK_API_KEY`（SNS取得で使用）
- `GROK_MANAGEMENT_API_KEY` / `GROK_MANAGEMENT_TEAM_ID`（運用画面のGrok残高表示で使用）
- `GROK_MANAGEMENT_API_BASE_URL`（既定: `https://management-api.x.ai`）
- `GROK_MODEL_FAST` / `GROK_MODEL_REASONING`（SNS取得モデル）
- `GROK_SNS_ENABLED` / `GROK_SNS_SCHEDULED_TIME` / `GROK_SNS_PER_TICKER_COOLDOWN_HOURS` / `GROK_SNS_PROMPT_TEMPLATE`（SNS取得運用設定）
- `WATCHLIST_REGISTRATION_BACKFILL_ENABLED`（既定: 無効。`true` の場合のみウォッチリスト登録直後バックフィルを実行）

必要な権限（API実行SA）:

- `roles/run.developer`（Cloud Run Jobs 実行/参照）
- `roles/logging.viewer`（スキップ理由集計）

`google-cloud-firestore` と `firebase-admin` が必要なため、`pip install -e ".[gcp]"` を事前に実行してください。

## テスト実行

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

## Firestoreマイグレーション（Issue 02）

```bash
PYTHONPATH=src python scripts/migrate_firestore_v0001.py --project-id <GCP_PROJECT_ID>
```

`--project-id` を省略する場合は、`.env` または環境変数で `FIRESTORE_PROJECT_ID` を設定してください。

## 日次ジョブ実行（Issue 06〜12 / 18）

Firestore `watchlist` を読み込んで、`daily_metrics` / `metric_medians` / `signal_state` / `notification_log` へ保存する本番実行:

```bash
PYTHONPATH=src python scripts/run_daily_job.py
```

- `--stdout` 未指定時は `--discord-webhook-url` または `DISCORD_WEBHOOK_URL_DAILY`（fallback: `DISCORD_WEBHOOK_URL`）が必須です。
- `--execution-mode daily|at_21|all` を指定可能です（既定は `daily`）。
  - `daily`: `notify_timing=IMMEDIATE` の銘柄だけ通知対象
  - `at_21`: `notify_timing=AT_21` の銘柄だけ通知対象
  - `all`: `IMMEDIATE` と `AT_21` の両方を通知対象

Discord送信を明示する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --discord-webhook-url <DISCORD_WEBHOOK_URL_DAILY>
```

21時向け銘柄だけ実行する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --execution-mode at_21 --discord-webhook-url <DISCORD_WEBHOOK_URL_DAILY>
```

stdout送信を明示する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --stdout
```

通知チェック（cooldown無効・notification_log未記録）:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --stdout --no-notification-log
```

### 本番定期実行構成（2026-02-18 時点）

- タイムゾーン: `Asia/Tokyo`
- `sc-kabu-immediate-open`（平日8:00-11:59 毎分）: `kabu-immediate-open` を起動し、`immediate_schedule` の寄り付き帯/間隔一致時のみ `notify_timing=IMMEDIATE` を評価
- `sc-kabu-immediate-close`（平日13:00-16:59 毎分）: `kabu-immediate-close` を起動し、`immediate_schedule` の引け帯/間隔一致時のみ `notify_timing=IMMEDIATE` を評価
- `sc-kabu-daily`（平日18:00）: `kabu-daily` を実行し、`notify_timing=IMMEDIATE` 銘柄を評価
- `sc-kabu-daily-at21`（平日21:05）: `kabu-daily-at21` を実行し、`notify_timing=AT_21` 銘柄を評価
- `sc-kabu-intelligence`（平日21:05）: `kabu-intelligence` を実行し、IR更新を評価
- `sc-kabu-grok`（毎分）: `kabu-grok` を起動し、Grok定時（`grok_sns.scheduled_time`）一致時のみSNS取得を評価
- `sc-kabu-backfill-incremental`（平日21:15）: `kabu-backfill-incremental` を実行し、`daily_metrics` 欠損/遅延を増分補完
- `sc-kabu-earnings-weekly`（土曜21:00）: `kabu-earnings-weekly` を実行
- `sc-kabu-earnings-tomorrow`（毎日21:00）: `kabu-earnings-tomorrow` を実行

補足:
- 増分バックフィルJobは `J-Quants APIキー` の Secret（既定: `jquants-api-key`）が利用可能な場合のみ作成されます。
- Grok Jobは `GROK_API_KEY` の Secret（既定: `grok-api-key`）が利用可能な場合のみ作成されます。
- `scripts/setup_scheduler.sh` 実行時に `JQUANTS_API_KEY`（環境変数または `.env`）があると、Secretへ最新バージョンとして登録されます。
- `scripts/setup_scheduler.sh` は既定で IR/SNS のWebhook Secretを分離します（`<SECRET_NAME>-intelligence-ir` / `<SECRET_NAME>-intelligence-sns`）。
- 共通Secretを使う場合は `INTELLIGENCE_IR_SECRET_NAME` / `INTELLIGENCE_SNS_SECRET_NAME` に `SECRET_NAME` と同じ値を指定します。

日次ジョブで通知が送信されるのは、以下のいずれかに該当した場合のみです。

- 割安シグナル成立（`1Y+3M` / `3M+1W` / `1Y+1W` / `1Y+3M+1W`）
- `always_notify_enabled=true` の銘柄で割安未成立（`PER状況` / `PSR状況`）
- 欠損発生（`【データ不明】`）
- クールダウン時間（デフォルト2時間）を超過、または通常→強への遷移

そのため、ジョブが成功していても `sent=0` は正常です（当日条件に一致する銘柄がなく、かつ常時通知対象がないケース）。

## 決算通知ジョブ実行

Firestoreの `watchlist` / `earnings_calendar` を使って通知する実行コマンド:

```bash
PYTHONPATH=src python scripts/run_earnings_job.py --job weekly --discord-webhook-url <DISCORD_WEBHOOK_URL_EARNINGS>
PYTHONPATH=src python scripts/run_earnings_job.py --job tomorrow --discord-webhook-url <DISCORD_WEBHOOK_URL_EARNINGS>
```

- `weekly`: 土曜21時（JST）想定。来週分を `今週決算` カテゴリで通知。
- `tomorrow`: 毎日21時（JST）想定。翌日分を `明日決算` カテゴリで通知。
- `--discord-webhook-url` 未指定時は `DISCORD_WEBHOOK_URL_EARNINGS`（fallback: `DISCORD_WEBHOOK_URL`）を利用。

## J-Quants v2 バックフィル

`daily_metrics` の過去データを J-Quants v2（Light）から補完する実行コマンド:

```bash
PYTHONPATH=src python scripts/run_backfill_daily_metrics.py --from-date 2025-02-01 --to-date 2026-02-18 --dry-run
PYTHONPATH=src python scripts/run_backfill_daily_metrics.py --from-date 2025-02-01 --to-date 2026-02-18
```

- APIキーは `JQUANTS_API_KEY`（環境変数）または `--api-key` で指定。
- `--tickers 3984:TSE,6238:TSE` で対象銘柄を絞り込み可能。
- 一括バックフィルは `daily_metrics` を補完し、増分バックフィル実行時は `metric_medians` / `signal_state` の最新再計算まで行う。

増分バックフィル（通常運用）:

```bash
PYTHONPATH=src python scripts/run_incremental_backfill_job.py --dry-run
PYTHONPATH=src python scripts/run_incremental_backfill_job.py
```

- 最新 `daily_metrics` から差分だけ再取得（既定 `overlap_days=7`）。
- 履歴ゼロ銘柄は初回 `initial_lookback_days=400` を取得。
- 実行後に `metric_medians` / `signal_state` の最新を再計算。

## IR/SNS/AI通知ジョブ実行

ウォッチリストの `ir_urls` / `x_official_account` / `x_executive_accounts` を監視し、`IR更新` / `SNS注目` / `AI注目` を通知する実行コマンド:

```bash
PYTHONPATH=src python scripts/run_intelligence_job.py --discord-webhook-url-ir <DISCORD_WEBHOOK_URL_INTELLIGENCE_IR> --discord-webhook-url-sns <DISCORD_WEBHOOK_URL_INTELLIGENCE_SNS>
```

- `AI_NOTIFICATIONS_ENABLED=true` かつ銘柄設定 `ai_enabled=true` の場合に `AI注目` を送信。
- SNS監視（Grok）には `GROK_API_KEY` が必要（未設定時は `【データ不明】` 通知）。
- モデルは `GROK_MODEL_FAST`（既定: `grok-4-1-fast-non-reasoning`）を優先し、抽出失敗時に `GROK_MODEL_REASONING`（既定: `grok-4-1-fast-reasoning`）をフォールバック利用。
- `GROK_SNS_ENABLED=true` の場合のみGrok取得を実行し、`GROK_SNS_SCHEDULED_TIME`（JST）と実行時刻が一致した時だけSNS取得を行います。
- `GROK_SNS_PER_TICKER_COOLDOWN_HOURS` の間は、同一銘柄の直近 `SNS注目` 通知がある場合に再取得をスキップします。
- 通知先は `DISCORD_WEBHOOK_URL_INTELLIGENCE_IR`（IR系）/ `DISCORD_WEBHOOK_URL_INTELLIGENCE_SNS`（SNS/AI系）で分離可能です。
- AI要約は `Vertex AI Gemini` を利用（既定: `VERTEX_AI_LOCATION=global`, `VERTEX_AI_MODEL=gemini-2.0-flash-001`）。
- IRリンク先は HTML/PDF 本文を取得し、本文テキストを要約対象に含める。
- `--execution-mode daily|at_21` で通知時間フィルタを選択可能。

## Web E2E（W12）

```bash
cd web
npm install
npm run test:e2e:install
npm run test:e2e
E2E_API_PYTHON=../.venv/bin/python npm run test:e2e:api
```

- 詳細: `web/README.md`
- ステージング反映手順: `docs/03_運用/Web_E2Eテストとステージング反映手順.md`
- 日常運用コマンド一覧: `docs/03_運用/日常運用コマンド一覧.md`
- 依頼主向け手順書: `docs/04_利用ガイド/トレーダー向け_使い方手順書.md`（管理画面 `/guide` からも参照可能）

## Discord疎通テスト

```bash
PYTHONPATH=src python scripts/send_discord_test_notification.py --webhook-url <DISCORD_WEBHOOK_URL>
```

`--webhook-url` 未指定時は `DISCORD_WEBHOOK_URL` を利用します。

## ドキュメント運用

- 現行仕様は `docs/README.md` の「正本（運用中）」を参照。
- 完了済みの受け入れ基準や旧版は `docs/90_アーカイブ/` を参照。
- `docs/` を更新したら `cd web && npm run sync:help-docs` で `/guide` 用データを同期し、`npm run dev` で表示確認する。
- `npm run dev` / `npm run build` / `npm run test:e2e` は同期を自動実行するが、ドキュメント単独更新時は手動同期を先に実施する。

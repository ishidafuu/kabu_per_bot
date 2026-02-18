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

- `--stdout` 未指定時は `--discord-webhook-url` または `DISCORD_WEBHOOK_URL` が必須です。
- `--execution-mode daily|at_21|all` を指定可能です（既定は `daily`）。
  - `daily`: `notify_timing=IMMEDIATE` の銘柄だけ通知対象
  - `at_21`: `notify_timing=AT_21` の銘柄だけ通知対象
  - `all`: `IMMEDIATE` と `AT_21` の両方を通知対象

Discord送信を明示する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --discord-webhook-url <DISCORD_WEBHOOK_URL>
```

21時向け銘柄だけ実行する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --execution-mode at_21 --discord-webhook-url <DISCORD_WEBHOOK_URL>
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
- `sc-kabu-daily`（平日18:00）: `kabu-daily` を実行し、`notify_timing=IMMEDIATE` 銘柄を評価
- `sc-kabu-daily-at21`（平日21:05）: `kabu-daily-at21` を実行し、`notify_timing=AT_21` 銘柄を評価
- `sc-kabu-earnings-weekly`（土曜21:00）: `kabu-earnings-weekly` を実行
- `sc-kabu-earnings-tomorrow`（毎日21:00）: `kabu-earnings-tomorrow` を実行

日次ジョブで通知が送信されるのは、以下のいずれかに該当した場合のみです。

- 割安シグナル成立（`1Y+3M` / `3M+1W` / `1Y+1W` / `1Y+3M+1W`）
- `always_notify_enabled=true` の銘柄で割安未成立（`PER状況` / `PSR状況`）
- 欠損発生（`【データ不明】`）
- 2時間クールダウンを超過、または通常→強への遷移

そのため、ジョブが成功していても `sent=0` は正常です（当日条件に一致する銘柄がなく、かつ常時通知対象がないケース）。

## 決算通知ジョブ実行（Issue 15）

Firestoreの `watchlist` / `earnings_calendar` を使って通知する実行コマンド:

```bash
PYTHONPATH=src python scripts/run_earnings_job.py --job weekly --discord-webhook-url <DISCORD_WEBHOOK_URL>
PYTHONPATH=src python scripts/run_earnings_job.py --job tomorrow --discord-webhook-url <DISCORD_WEBHOOK_URL>
```

- `weekly`: 土曜21時（JST）想定。来週分を `今週決算` カテゴリで通知。
- `tomorrow`: 毎日21時（JST）想定。翌日分を `明日決算` カテゴリで通知。
- `--discord-webhook-url` 未指定時は `DISCORD_WEBHOOK_URL` を利用。

## J-Quants v2 バックフィル（Issue BF-01〜03 着手）

`daily_metrics` の過去データを J-Quants v2（Light）から補完する実行コマンド:

```bash
PYTHONPATH=src python scripts/run_backfill_daily_metrics.py --from-date 2025-02-01 --to-date 2026-02-18 --dry-run
PYTHONPATH=src python scripts/run_backfill_daily_metrics.py --from-date 2025-02-01 --to-date 2026-02-18
```

- APIキーは `JQUANTS_API_KEY`（環境変数）または `--api-key` で指定。
- `--tickers 3984:TSE,6238:TSE` で対象銘柄を絞り込み可能。
- 現時点の着手範囲は `daily_metrics` への投入まで（中央値・シグナル再計算は次Issue）。

## IR/SNS/AI通知ジョブ実行

ウォッチリストの `ir_urls` / `x_official_account` / `x_executive_accounts` を監視し、`IR更新` / `SNS注目` / `AI注目` を通知する実行コマンド:

```bash
PYTHONPATH=src python scripts/run_intelligence_job.py --discord-webhook-url <DISCORD_WEBHOOK_URL>
```

- `AI_NOTIFICATIONS_ENABLED=true` かつ銘柄設定 `ai_enabled=true` の場合に `AI注目` を送信。
- X監視には `X_API_BEARER_TOKEN` が必要。
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

## Discord疎通テスト（Issue 12）

```bash
PYTHONPATH=src python scripts/send_discord_test_notification.py --webhook-url <DISCORD_WEBHOOK_URL>
```

`--webhook-url` 未指定時は `DISCORD_WEBHOOK_URL` 環境変数を利用します。

## 実装スコープ対応

- Issue 04: watchlist履歴記録
- Issue 05〜10: データ取得IF、PER/PSR計算、中央値、under/強通知、streak、クールダウン
- Issue 11〜12: 通知文面整形、Discord通知アダプタ
- Issue 14〜18（骨格）: 決算選定、欠損通知、通知ログ、日次E2Eパイプライン

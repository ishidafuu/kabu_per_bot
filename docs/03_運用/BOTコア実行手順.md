# BOTコア実行手順（Issue 04〜18骨格）

## 1. 目的

- BOTコア（指標計算・通知）のローカル実行手順を明文化する。
- Discord疎通と主要ロジックのテスト実行を標準化する。

## 2. 前提

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e ".[gcp]"
```

## 3. テスト

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

重点テスト対象:

- under判定/強通知
- streak更新
- クールダウン（デフォルト2時間、全体設定で変更可）
- 通知フォーマット
- 欠損通知（`【データ不明】`）

## 4. ジョブ実行（日次本番フロー）

```bash
PYTHONPATH=src python scripts/run_daily_job.py
```

- Firestore `watchlist` を読み込み、日次パイプラインを実行する。
- 実行結果は `daily_metrics` / `metric_medians` / `signal_state` / `notification_log` に保存される。
- `--stdout` 未指定時は `--discord-webhook-url` または `DISCORD_WEBHOOK_URL` が必要。
- `JQUANTS_API_KEY` または `--jquants-api-key` を指定した場合、市場データ取得で `J-Quants v2` を最優先で試行し、その後に `株探 → Yahoo!ファイナンス` へフォールバックする。
- `--execution-mode daily|at_21|all` で通知タイミング対象を選択できる（既定: `daily`）。
  - `daily`: `notify_timing=IMMEDIATE` の銘柄のみ
  - `at_21`: `notify_timing=AT_21` の銘柄のみ
  - `all`: 両方
- 標準出力のJSONは `processed` / `sent` / `skipped` / `errors` を返す。
- 通知条件（割安/データ不明/常時通知ON時の状況通知）に一致しなければ `sent=0` でも正常（ジョブ成功）である。
- クールダウン時間は `global_settings/runtime.cooldown_hours` があればそれを優先し、未設定時は `COOLDOWN_HOURS` を使用する。

stdout送信を明示する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --stdout
```

21時向け銘柄（`notify_timing=AT_21`）だけ実行する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --execution-mode at_21 --discord-webhook-url <DISCORD_WEBHOOK_URL>
```

定期実行（Cloud Run Jobs + Scheduler）での既定構成:

- `kabu-daily` <- `sc-kabu-daily`（平日18:00 JST）
- `kabu-daily-at21` <- `sc-kabu-daily-at21`（平日21:05 JST）
- `kabu-backfill-incremental` <- `sc-kabu-backfill-incremental`（平日21:15 JST）
- `kabu-earnings-weekly` <- `sc-kabu-earnings-weekly`（土曜21:00 JST）
- `kabu-earnings-tomorrow` <- `sc-kabu-earnings-tomorrow`（毎日21:00 JST）

補足:
- `kabu-backfill-incremental` は `J-Quants APIキー` の Secret（既定: `jquants-api-key`）が利用可能な場合のみ作成される。

確認コマンド:

```bash
gcloud run jobs executions list --job=kabu-daily --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud run jobs executions list --job=kabu-daily-at21 --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud scheduler jobs list --location=asia-northeast1 --project=<GCP_PROJECT_ID>
```

## 5. Discord疎通

```bash
PYTHONPATH=src python scripts/send_discord_test_notification.py --webhook-url <DISCORD_WEBHOOK_URL>
```

または:

```bash
export DISCORD_WEBHOOK_URL=<DISCORD_WEBHOOK_URL>
PYTHONPATH=src python scripts/send_discord_test_notification.py
```

## 6. 決算通知ジョブ（Issue 15）

```bash
PYTHONPATH=src python scripts/run_earnings_job.py --job weekly --discord-webhook-url <DISCORD_WEBHOOK_URL>
PYTHONPATH=src python scripts/run_earnings_job.py --job tomorrow --discord-webhook-url <DISCORD_WEBHOOK_URL>
```

- `weekly`: 土曜21時（JST）想定。来週決算を `今週決算` として通知。
- `tomorrow`: 毎日21時（JST）想定。翌日決算を `明日決算` として通知。
- `FIRESTORE_PROJECT_ID` と `DISCORD_WEBHOOK_URL` を利用する。

## 7. IR/SNS/AI通知ジョブ

```bash
PYTHONPATH=src python scripts/run_intelligence_job.py --discord-webhook-url <DISCORD_WEBHOOK_URL>
```

- `AI_NOTIFICATIONS_ENABLED=true` かつ銘柄設定 `ai_enabled=true` で `【AI注目】` を送信。
- SNS監視には `X_API_BEARER_TOKEN` が必要（未設定時は `【データ不明】` 通知）。
- AI要約は `Vertex AI Gemini` を利用し、`VERTEX_AI_LOCATION` / `VERTEX_AI_MODEL` で変更できる。
- IRリンク先の HTML/PDF 本文を取得し、本文テキストを要約対象として扱う。
- `--execution-mode daily|at_21` で通知時間フィルタを指定可能。

## 8. マイグレーション

```bash
PYTHONPATH=src python scripts/migrate_firestore_v0001.py --project-id <GCP_PROJECT_ID>
```

## 9. デプロイ前機械チェック（W12）

Hosting / Cloud Run へ反映する前に、ローカルで事前チェックだけ実行する。

```bash
cd /Users/ishidafuu/Documents/repository/kabu_per_bot
bash scripts/preflight_deploy_check.sh
```

- `python/node/npm/git` の存在確認を行う。
- `web` の `npm run build` 成功を確認する。
- 主要環境変数（`.env`, `web/.env.local`）の未設定は `WARN` 表示で通知する。
- 終了コード `0`: 事前チェック通過、`1`: 失敗あり（要修正）。

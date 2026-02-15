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
- クールダウン2時間
- 通知フォーマット
- 欠損通知（`【データ不明】`）

## 4. ジョブ実行（日次本番フロー）

```bash
PYTHONPATH=src python scripts/run_daily_job.py
```

- Firestore `watchlist` を読み込み、日次パイプラインを実行する。
- 実行結果は `daily_metrics` / `metric_medians` / `signal_state` / `notification_log` に保存される。

stdout送信を明示する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --stdout
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

## 7. マイグレーション

```bash
PYTHONPATH=src python scripts/migrate_firestore_v0001.py --project-id <GCP_PROJECT_ID>
```

## 8. デプロイ前機械チェック（W12）

Hosting / Cloud Run へ反映する前に、ローカルで事前チェックだけ実行する。

```bash
cd /Users/ishidafuu/Documents/repository/kabu_per_bot-docs-finalize
bash scripts/preflight_deploy_check.sh
```

- `python/node/npm/git` の存在確認を行う。
- `web` の `npm run build` 成功を確認する。
- 主要環境変数（`.env`, `web/.env.local`）の未設定は `WARN` 表示で通知する。
- 終了コード `0`: 事前チェック通過、`1`: 失敗あり（要修正）。

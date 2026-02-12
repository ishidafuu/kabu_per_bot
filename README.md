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

## 日次ジョブ実行（Issue 06〜12 / 18の骨格）

ローカル検証用のデモ実行:

```bash
PYTHONPATH=src python scripts/run_daily_job.py
```

Discord送信まで疎通確認する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --discord-webhook-url <DISCORD_WEBHOOK_URL>
```

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

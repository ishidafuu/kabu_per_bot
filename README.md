# kabu_per_bot
株式監視BOT

## 開発メモ（Issue 01）

### セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e ".[gcp]"
```

### 起動確認

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

### テスト

```bash
python -m unittest discover -s tests
```

### Firestoreマイグレーション（Issue 02）

```bash
PYTHONPATH=src python scripts/migrate_firestore_v0001.py --project-id <GCP_PROJECT_ID>
```

`--project-id` を省略する場合は、`.env` または環境変数で `FIRESTORE_PROJECT_ID` を設定してください。

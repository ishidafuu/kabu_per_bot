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

### テスト

```bash
python -m unittest discover -s tests
```

### Firestoreマイグレーション（Issue 02）

```bash
PYTHONPATH=src python scripts/migrate_firestore_v0001.py --project-id <GCP_PROJECT_ID>
```

`--project-id` を省略する場合は、`.env` または環境変数で `FIRESTORE_PROJECT_ID` を設定してください。

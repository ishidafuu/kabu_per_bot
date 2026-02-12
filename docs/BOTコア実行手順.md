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

## 4. ジョブ実行（ローカルデモ）

```bash
PYTHONPATH=src python scripts/run_daily_job.py
```

- 日次パイプライン（Issue 18骨格）をローカルで実行する。
- デモ市場データを用いて、計算〜通知判定〜送信処理を検証する。

## 5. Discord疎通

```bash
PYTHONPATH=src python scripts/send_discord_test_notification.py --webhook-url <DISCORD_WEBHOOK_URL>
```

または:

```bash
export DISCORD_WEBHOOK_URL=<DISCORD_WEBHOOK_URL>
PYTHONPATH=src python scripts/send_discord_test_notification.py
```

## 6. マイグレーション

```bash
PYTHONPATH=src python scripts/migrate_firestore_v0001.py --project-id <GCP_PROJECT_ID>
```

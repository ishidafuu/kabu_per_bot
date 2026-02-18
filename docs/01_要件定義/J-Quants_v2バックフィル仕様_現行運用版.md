# J-Quants v2 バックフィル仕様（現行運用版）

最終更新: 2026-02-18（JST）

このドキュメントは、J-Quantsバックフィルの現行運用仕様をまとめた正本です。  
Issue分割の受け入れ基準チェックリストは完了済みのためアーカイブへ退避しています。

- アーカイブ: `docs/90_アーカイブ/2026-02-18/J-Quants_v2バックフィル仕様_受け入れ基準詳細_2026-02-18時点.md`

## 1. 目的

- `daily_metrics` の欠損/遅延をJ-Quants v2で補完し、中央値判定とシグナル判定の精度を維持する。

## 2. 現行実装範囲

1. `J-Quants v2` クライアント実装（APIキー認証、ページネーション、例外化）
2. バックフィル変換ロジック（終値と予想値の突合）
3. 一括バックフィルCLI（`scripts/run_backfill_daily_metrics.py`）
4. 増分バックフィルCLI（`scripts/run_incremental_backfill_job.py`）
5. 実行後の `metric_medians` / `signal_state` 最新再計算

## 3. 実行コマンド

一括バックフィル:

```bash
PYTHONPATH=src python scripts/run_backfill_daily_metrics.py --from-date 2025-02-01 --to-date 2026-02-18 --dry-run
PYTHONPATH=src python scripts/run_backfill_daily_metrics.py --from-date 2025-02-01 --to-date 2026-02-18
```

増分バックフィル:

```bash
PYTHONPATH=src python scripts/run_incremental_backfill_job.py --dry-run
PYTHONPATH=src python scripts/run_incremental_backfill_job.py
```

## 4. 失敗時ポリシー

1. APIキー未設定は明示的エラーで停止する
2. J-Quants API失敗時は例外/ログで追跡可能にする
3. 不正な銘柄コード・不正日付は入力エラーとして扱う
4. サイレント失敗は禁止

## 5. 運用確認ポイント

1. dry-runで対象銘柄数と生成件数を確認する
2. 実行後に `daily_metrics` が更新されていることを確認する
3. 必要に応じて `metric_medians` / `signal_state` の最新日付を確認する
4. 通知系ジョブと混同しない（バックフィルは通知送信そのものを目的としない）

# AGENTS.md

このファイルは、本リポジトリで作業するエージェント向けの実装・運用ルールを定義する。  
最終更新: 2026-02-21（JST）

## 1. 基本方針

- 対話・説明・Issue/PR本文は日本語で記述する。
- コミットメッセージは日本語で記述する。
- 実装優先度は `MVPコアの安定運用 > 既存運用機能の改善 > 新規拡張` とする。
- 「実装済みだが運用調整中」の機能（IR/SNS/AI、増分バックフィル）は、既存挙動を壊さない範囲で改善する。
- 仕様判断で迷った場合は、まず `docs/README.md` の「正本（運用中）」を参照する。

## 2. 仕様の正本

- 仕様・設計・運用の正本は以下とする（優先参照順）。
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/README.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/01_要件定義/MVP仕様_現行運用版.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/01_要件定義/J-Quants_v2バックフィル仕様_現行運用版.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/02_設計/技術スタック定義.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/02_設計/Firestoreスキーマ設計.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/02_設計/Web管理画面_仕様（画面一覧・API一覧）.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/03_運用/BOTコア実行手順.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/03_運用/日常運用コマンド一覧.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/03_運用/Web_E2Eテストとステージング反映手順.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/03_運用/運用開始チェックリスト.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/04_利用ガイド/トレーダー向け_使い方手順書.md`
- `docs/90_アーカイブ/` は履歴参照専用とし、現行仕様判断には使わない。

## 3. 現在のスコープ（2026-02時点）

### 3.1 MVPコア（最優先）

- ウォッチリスト管理（最大100銘柄、履歴管理含む）
- PER/PSR日次計算と中央値判定（1W/3M/1Y）
- 割安通知、強通知、クールダウン制御
- `【データ不明】` 通知を含む欠損可視化
- Discord通知配信
- FastAPI + React Web管理画面（ダッシュボード、履歴、通知ログ）

### 3.2 運用中の拡張機能（既存維持を前提に改善）

- 決算通知（今週/明日）
- IR通知（intelligence job）
- SNS/AI注目通知（Grok + Vertex AI Gemini）
- 増分バックフィル（J-Quants v2）
- `/ops` からの運用操作（ジョブ実行、実行履歴、設定更新）

### 3.3 当面の対象外

- 上記正本ドキュメントに未定義の新規データソース常設追加
- 通知カテゴリの大幅な再設計
- 運用要件なしの大規模UI刷新

## 4. 実装ルール

- サイレント失敗を禁止する。取得失敗・欠損は必ずログまたは `【データ不明】` 通知で可視化する。
- 時刻基準は `JST（Asia/Tokyo）` 固定で扱う。
- 既定しきい値は以下を使用する。
  - 1W=5営業日
  - 3M=63営業日
  - 1Y=252営業日
  - クールダウン=2時間
- 設定値の優先順位は `global_settings/runtime > 環境変数(.env) > コード既定値` とする。
- 通知フォーマットは要件定義書の規定を崩さない。
- 通知チャネルは `Discord` を使用する。
- 市場データ取得は交換可能なインターフェースで実装し、優先順は以下を維持する。
  - （`JQUANTS_API_KEY` 設定時）J-Quants v2 → 株探 → Yahoo!ファイナンス
  - （未設定時）株探 → Yahoo!ファイナンス
  - 四季報onlineは日次取得経路から除外する
- AI要約は `Vertex AI Gemini` を標準とする。SNS取得は現行運用のGrok設定を尊重する。

## 5. Issue運用

- 1 Issue = 1つの目的に限定する。
- 各Issueには最低限以下を含める。
  - 概要
  - 背景/目的
  - スコープ
  - 受け入れ基準（チェックリスト）
  - 依存Issue
- 実装前に依存Issueの完了状態を確認する。
- 追加要件や仕様変更は、着手前に受け入れ基準をIssueへ追記する。

## 6. コミット/ブランチ運用

- コミットメッセージは日本語で、`1コミット1意図` を原則とする。
- 対応完了した変更は、依頼単位で即コミットする（不要なまとめコミットを避ける）。
- マージは線形履歴を維持する（マージコミット禁止）。`git merge --ff-only` を基本とし、必要時は `git rebase` で取り込む。
- 推奨プレフィックス:
  - `feat:`
  - `fix:`
  - `refactor:`
  - `test:`
  - `docs:`

## 7. テスト/品質ゲート

- 変更前後で、影響範囲に応じて以下を実行する。

### 7.1 Backend/Pipeline変更時（必須）

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

- 重要ロジック（under判定、強通知、streak、クールダウン、通知文面、欠損系）のテストを優先追加する。

### 7.2 Web変更時（必須）

```bash
cd web
npm run lint
npm run test:e2e
E2E_API_PYTHON=../.venv/bin/python npm run test:e2e:api
```

- 変更規模が小さい場合でも、最低 `npm run lint` は実行する。

### 7.3 docs更新時（必須）

```bash
cd web
npm run sync:help-docs
```

- `/guide` 表示対象のため、`docs/` 更新時は同期結果も同一PRに含める。

## 8. PRレビュー観点

- 受け入れ基準を満たしているか。
- 仕様書と実装の差分が説明されているか。
- 欠損時挙動が明示されているか。
- 通知重複抑制と状態遷移（通常→強）が意図通りか。
- ログで追跡可能か（いつ何を通知したか）。

## 9. ドキュメント更新ルール

- 振る舞いを変える変更をした場合、関連する `docs/*.md` を同じPRで更新する。
- 仕様変更を決めた場合、少なくとも以下を更新する。
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/01_要件定義/MVP仕様_現行運用版.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/README.md`（正本構成が変わる場合）

## 10. デプロイ運用ルール（Cloud Run / Hosting）

- Firebase Hosting から Cloud Run API を直接呼び出す運用のため、Cloud Runデプロイ時は `--allow-unauthenticated` を必ず指定する。
- `--no-allow-unauthenticated` は使用しない（WebからAPIが `403` になりやすい）。
- Cloud Runデプロイ後は IAM を確認し、`allUsers` に `roles/run.invoker` があることを確認する。
- `allUsers` の invoker が欠けている場合は、以下で復旧する。
  - `gcloud run services add-iam-policy-binding <SERVICE_NAME> --region asia-northeast1 --member="allUsers" --role="roles/run.invoker"`
- デプロイ前は以下の事前チェックを推奨する。
  - `bash scripts/preflight_deploy_check.sh`

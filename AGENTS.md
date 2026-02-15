# AGENTS.md

このファイルは、本リポジトリで作業するエージェント向けの実装・運用ルールを定義する。

## 1. 基本方針

- 対話・説明・Issue/PR本文は日本語で記述する。
- コミットメッセージは日本語で記述する。
- 実装はMVP優先で進める。MVP外（IR/SNS/AI注目）は別マイルストーンで扱う。
- 仕様の正本は以下とする。
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/MVP仕様分解_受け入れ基準.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/技術スタック定義.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/Firestoreスキーマ設計.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/Web管理画面_仕様（画面一覧・API一覧）.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/BOTコア実行手順.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/Web_E2Eテストとステージング反映手順.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/トレーダー向け_使い方手順書.md`
  - `/Users/ishidafuu/Documents/repository/kabu_per_bot/docs/運用開始チェックリスト.md`

## 2. スコープ管理

- まずは以下のMVPを満たす実装を優先する。
  - ウォッチリスト管理（最大100銘柄）
  - PER/PSR日次計算と中央値判定（1W/3M/1Y）
  - 通知（PER/PSR、決算、データ不明）
  - Discord配信
  - クールダウン（2時間）
- 追加要件や仕様変更は、必ずIssueに受け入れ基準を追記してから着手する。

## 3. 実装ルール

- サイレント失敗を禁止する。取得失敗・欠損は必ずログまたは `【データ不明】` 通知で可視化する。
- 時刻基準は当面JST固定とする。
- しきい値の既定値は以下を使用する。
  - 1W=5営業日
  - 3M=63営業日
  - 1Y=252営業日
  - クールダウン=2時間
- 通知フォーマットは要件定義書の規定を崩さない。
- 通知チャネルは `Discord` を使用する。
- データソースは交換可能なインターフェースで実装し、優先順は以下。
  - 四季報online → 株探 → Yahoo!ファイナンス
- SNS取得（第2段階）は `X API` を標準とする。
- AI要約（第2段階）は `Vertex AI Gemini` を標準とし、Grokは比較PoCで必要性が確認された場合のみ検討する。

## 4. Issue運用

- 1 Issue = 1つの目的に限定する。
- 各Issueには最低限以下を含める。
  - 概要
  - 背景/目的
  - スコープ
  - 受け入れ基準（チェックリスト）
  - 依存Issue
- 実装前に依存Issueの完了状態を確認する。

## 5. コミット/ブランチ運用

- コミットメッセージは日本語で、1コミット1意図を原則とする。
- 基本運用として、対応が完了した変更はできるだけその場で即コミットする（不要なまとめコミットを避ける）。
- マージは線形履歴を維持する（マージコミット禁止）。`git merge --ff-only` を基本とし、必要時は `git rebase` で取り込む。
- 推奨プレフィックス:
  - `feat:`
  - `fix:`
  - `refactor:`
  - `test:`
  - `docs:`
- 例:
  - `feat: ウォッチリスト追加APIと100件上限制御を実装`
  - `fix: 強通知への遷移時にクールダウンを誤適用する不具合を修正`

## 6. テスト/品質

- 重要ロジック（under判定、強通知、streak、クールダウン）は単体テストを作成する。
- 通知文面のフォーマット崩れを防ぐテストを作成する。
- 失敗系（欠損、外部API失敗）のテストを優先的に追加する。
- テストやlintコマンドはプロジェクト確定後にこのファイルへ追記する。

## 7. PRレビュー観点

- 受け入れ基準を満たしているか。
- 仕様書と実装の差分が説明されているか。
- 欠損時挙動が明示されているか。
- 通知重複抑制と状態遷移（通常→強）が意図通りか。
- ログで追跡可能か（いつ何を通知したか）。

## 8. ドキュメント更新ルール

- 振る舞いを変える変更をした場合、関連する `docs/*.md` を同じPRで更新する。
- 仕様未確定項目を決めた場合、`MVP仕様分解_受け入れ基準.md` の未確定セクションを更新する。

## 9. デプロイ運用ルール（Cloud Run / Hosting）

- Firebase Hosting から Cloud Run API を直接呼び出す運用のため、Cloud Run デプロイ時は `--allow-unauthenticated` を必ず指定する。
- `--no-allow-unauthenticated` は使用しない（適用すると Web から API が `403` になりやすい）。
- Cloud Run デプロイ後は必ず IAM を確認し、`allUsers` に `roles/run.invoker` があることを確認する。
- もし `allUsers` の invoker が欠けている場合は、以下で即時復旧する。
  - `gcloud run services add-iam-policy-binding <SERVICE_NAME> --region asia-northeast1 --member="allUsers" --role="roles/run.invoker"`

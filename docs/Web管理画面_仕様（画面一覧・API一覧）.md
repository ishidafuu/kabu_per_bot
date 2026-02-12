# Web管理画面 仕様（画面一覧・API一覧）

## 1. 目的

- Python実装済みの監視ロジックを、Web UIで安全に操作できるようにする
- ウォッチリスト管理、履歴確認、通知ログ確認をブラウザで完結させる

## 2. 技術構成（確定）

1. フロントエンド: React + TypeScript（Vite）
2. フロント配信: Firebase Hosting
3. API: FastAPI（Python）+ Cloud Run
4. 認証: Firebase Authentication
5. データ: Cloud Firestore

## 3. 画面一覧（初版）

### 3.1 ログイン画面

- 機能:
  - Firebase Auth でログイン
  - 認証成功後にダッシュボードへ遷移

### 3.2 ダッシュボード

- 表示:
  - 監視銘柄数（上限100）
  - 本日のPER/PSR通知件数
  - 本日のデータ不明件数
  - 直近失敗ジョブ有無

### 3.3 ウォッチリスト一覧画面

- 表示項目:
  - ticker
  - 会社名
  - 監視方式（PER/PSR）
  - 通知先（DISCORD/LINE/BOTH/OFF）
  - 通知時間（IMMEDIATE/AT_21/OFF）
  - 有効状態（is_active）
- 操作:
  - 追加
  - 編集
  - 削除
  - 絞り込み（ticker/会社名）

### 3.4 ウォッチリスト編集画面

- 入力:
  - ticker
  - 会社名
  - 監視方式
  - 通知先
  - 通知時間
  - AI通知ON/OFF
- バリデーション:
  - ticker形式 `1234:TSE`
  - 会社名必須
  - 101件目追加時はエラー表示

### 3.5 監視履歴画面（Issue 04以降）

- 表示:
  - 追加/削除履歴（日時、操作、理由）

### 3.6 通知ログ画面（Issue 17以降）

- 表示:
  - 通知カテゴリ
  - ticker
  - 条件キー
  - 送信時刻
  - チャネル

## 4. API一覧（初版）

ベースURL: `/api/v1`

### 4.1 ヘルスチェック

1. `GET /healthz`
  - 目的: 生存確認
  - 200レスポンス:
    - `{"status":"ok"}`

### 4.2 ウォッチリスト

1. `GET /watchlist`
  - 目的: 一覧取得
  - クエリ:
    - `q`（任意: ticker/name 部分一致）
    - `limit`（任意）
    - `offset`（任意）
  - 200レスポンス:
    - `items[]`
    - `total`

2. `GET /watchlist/{ticker}`
  - 目的: 詳細取得
  - 404: 該当なし

3. `POST /watchlist`
  - 目的: 追加
  - リクエスト:
    - `ticker`
    - `name`
    - `metric_type`
    - `notify_channel`
    - `notify_timing`
    - `ai_enabled`（任意）
    - `is_active`（任意）
  - 201: 作成成功
  - 409: 重複
  - 422: 入力不正
  - 429: 上限超過（100件）

4. `PATCH /watchlist/{ticker}`
  - 目的: 更新
  - リクエスト:
    - `name`（任意）
    - `metric_type`（任意）
    - `notify_channel`（任意）
    - `notify_timing`（任意）
    - `ai_enabled`（任意）
    - `is_active`（任意）
  - 200: 更新成功
  - 404: 該当なし

5. `DELETE /watchlist/{ticker}`
  - 目的: 削除
  - 204: 削除成功
  - 404: 該当なし

### 4.3 履歴/ログ（将来API）

1. `GET /watchlist/history`
  - Issue 04 で実装

2. `GET /notifications/logs`
  - Issue 17 で実装

## 5. 認証・認可

1. フロントは Firebase Auth でログインし ID トークンを取得
2. API リクエストは `Authorization: Bearer <id_token>` を付与
3. FastAPI 側で Firebase Admin SDK によりトークン検証
4. 未認証は `401`、権限不足は `403`

## 6. エラーコード方針

1. `400`: パラメータ不正
2. `401`: 未認証
3. `403`: 認可エラー
4. `404`: リソースなし
5. `409`: 重複
6. `422`: 入力バリデーション不正
7. `429`: 件数上限超過
8. `500`: 想定外エラー

## 7. 実装順（Web）

1. API基盤（FastAPI + 認証ミドルウェア + OpenAPI）
2. ウォッチリストAPI（GET/POST/PATCH/DELETE）
3. ログイン画面 + ウォッチリスト一覧/編集画面
4. ダッシュボード最小版
5. 履歴画面・通知ログ画面


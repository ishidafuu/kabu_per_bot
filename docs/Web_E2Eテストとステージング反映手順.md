# Web E2Eテストとステージング反映手順（W12）

## 1. 目的

- W12の受け入れ基準である「主要導線E2Eの再現実行」と「ステージング反映の最小手順」を固定する。
- 画面構成は W10（ダッシュボード）/W11（履歴・通知ログ）マージ後を前提とする。

## 2. E2Eケース一覧（主要導線）

1. ログイン:
   - モックログイン成功後に `/dashboard` へ遷移する。
2. ダッシュボード表示（W10）:
   - 監視銘柄数 / 当日通知件数 / データ不明件数 / 失敗ジョブ有無 を表示できる。
3. ウォッチリスト一覧:
   - 一覧が表示され、初期データが見える。
4. ウォッチリストCRUD:
   - 作成/編集/削除がUIから完了し、件数が変化する。
5. 履歴・通知ログ表示（W11）:
   - `/watchlist/history` と `/notifications/logs` が表示される。
   - ticker絞り込みが機能する。

実装ファイル:

- `web/e2e/web-flows.spec.ts`

## 3. ローカル再現手順（E2E）

前提:

- Node.js 20+ / npm
- 初回のみ Playwright Chromium をインストール

実行:

```bash
cd /Users/ishidafuu/Documents/repository/kabu_per_bot/web
npm install
npm run test:e2e:install
npm run test:e2e
```

補助コマンド:

```bash
npm run test:e2e:headed
npm run test:e2e:ui
```

補足:

- E2Eは `playwright.config.ts` で `VITE_USE_MOCK_API=true` / `VITE_USE_MOCK_AUTH=true` を使うため、バックエンド起動は不要。

## 4. ステージング反映（現行運用の最小手順）

### 4.1 事前条件

1. Firebase CLI にログイン済み:
   - `firebase login`
2. gcloud CLI にログイン済み:
   - `gcloud auth login`
3. ステージングの値を把握している:
   - `FIREBASE_STG_PROJECT_ID`
   - `STG_API_BASE_URL`（例: `https://<cloud-run-service-url>/api/v1`）

### 4.2 Webのみ変更（今回W12の標準手順）

1. E2Eを通す

```bash
cd /Users/ishidafuu/Documents/repository/kabu_per_bot/web
npm run test:e2e
```

2. ステージング向けにビルド

```bash
cd /Users/ishidafuu/Documents/repository/kabu_per_bot/web
VITE_USE_MOCK_API=false \
VITE_USE_MOCK_AUTH=false \
VITE_API_BASE_URL="<STG_API_BASE_URL>" \
npm run build
```

3. Firebase Hosting へ反映

```bash
cd /Users/ishidafuu/Documents/repository/kabu_per_bot
firebase use <FIREBASE_STG_PROJECT_ID>
firebase deploy --only hosting
```

### 4.3 API変更を含む場合（必要時のみ）

FastAPIに変更がある場合のみ、先にCloud Runを更新してから 4.2 を実施する。

```bash
gcloud config set project <GCP_PROJECT_ID>
gcloud run deploy <API_STG_SERVICE_NAME> \
  --image <ARTIFACT_REGISTRY_IMAGE_URI> \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated
```

## 5. 反映後の確認

1. ステージングURLでログインできる。
2. ダッシュボードにKPIが表示される。
3. ウォッチリストで作成/編集/削除ができる。
4. 履歴・通知ログが表示できる。

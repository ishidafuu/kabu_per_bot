# Webフロントエンド（W06〜W09）

`kabu_per_bot` の管理画面向けフロントエンドです。  
実装技術は `React + TypeScript + Vite`、認証は `Firebase Auth`、API連携は分離したクライアント層で扱います。

## 実装済みスコープ

- W06: `web/` 雛形、ルーティング、環境変数、APIクライアント分離
- W07: ログイン画面（Firebase Auth導線 + モック認証）
- W08: ウォッチリスト一覧（検索、ページング）
- W09: ウォッチリスト作成/編集/削除（409/422/429 エラー表示）

## 画面

- `/login`: ログイン画面
- `/watchlist`: ウォッチリスト管理（保護画面）

## 起動手順

```bash
cd web
npm install
npm run dev
```

ブラウザで [http://localhost:5173](http://localhost:5173) を開いてください。

## モックでの確認（バックエンド未接続時）

`.env` 未設定でも、以下の既定値でそのまま動作します。

- `VITE_USE_MOCK_API=true`
- `VITE_USE_MOCK_AUTH=true`

この場合はログイン画面で「モックログイン」を使って操作確認できます。

## 実API/Firebase接続

`.env.local` を作成して値を設定してください。

```bash
cp .env.example .env.local
```

| 変数名 | 例 | 用途 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | FastAPI のベースURL |
| `VITE_USE_MOCK_API` | `false` | `false` で実APIを使用 |
| `VITE_USE_MOCK_AUTH` | `false` | `false` で Firebase Auth を使用 |
| `VITE_FIREBASE_API_KEY` | `...` | Firebase設定 |
| `VITE_FIREBASE_AUTH_DOMAIN` | `...` | Firebase設定 |
| `VITE_FIREBASE_PROJECT_ID` | `...` | Firebase設定 |
| `VITE_FIREBASE_APP_ID` | `...` | Firebase設定 |
| `VITE_PAGE_SIZE` | `10` | 一覧のページサイズ |

## 品質確認

```bash
npm run lint
npm run build
```

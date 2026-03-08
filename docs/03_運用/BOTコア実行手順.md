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
- クールダウン（デフォルト2時間、全体設定で変更可）
- 通知フォーマット
- 欠損通知（`【データ不明】`）

通知フォーマット運用メモ（2026-02更新）:

- `PER割安` / `超PER割安` / `PER状況` / `PSR状況` は、先頭を `【】` 見出しではなくカテゴリ用アイコンで表示する。
- 上記通知は本文を複数行とし、主要項目のみアイコンを付ける（アイコン過多を避ける）。
- 上記通知は 1行目に `ticker + 会社名`、2行目に `優先度/推奨/判断`、3行目に日本語の要約文、4行目に圧縮した数値詳細を置き、数値の羅列より先に状態を読める並びにする。
- `SNS注目` は `🛰️ SNS注目` ヘッダ + 字下げの複数行で表示し、`[注目度|状況|Cat|影響]` を本文から分離して可読化する。
- `SNS注目` は抽出後に `公式 > 役員 > その他` の優先度で整列し、同一銘柄の上限件数に達する場合は公式/役員投稿を優先して採用する。
- `データ不明` は既存運用どおり `【データ不明】` 形式を維持する。
- `委員会評価` は「総合（自信/強さ）」「2軸の見方」「総合コメント」「観点別の理由（平文）」を表示し、初心者でも判断根拠を追える形式とする。

## 4. ジョブ実行（早見表 + 日次本番フロー）

### 4.1 ジョブ種別と実行パターン（早見表）

| 種別 | 実行スクリプト/引数 | 通知タイミング対象 | 実処理の実行条件 |
| --- | --- | --- | --- |
| 日次（IMMEDIATE） | `scripts/run_daily_job.py --execution-mode daily` | `notify_timing=IMMEDIATE` | 日次判定は常に実行（委員会評価は時刻一致時のみ） |
| 日次（AT_21） | `scripts/run_daily_job.py --execution-mode at_21` | `notify_timing=AT_21` | 日次判定は常に実行（委員会評価は時刻一致時のみ） |
| 日次（両方） | `scripts/run_daily_job.py --execution-mode all` | `IMMEDIATE` + `AT_21` | 日次判定は常に実行（委員会評価は時刻一致時のみ） |
| 寄り付き帯 | `scripts/run_immediate_window_job.py --window open` | `notify_timing=IMMEDIATE` | `immediate_schedule` の時間帯・間隔一致時のみ |
| 引け帯 | `scripts/run_immediate_window_job.py --window close` | `notify_timing=IMMEDIATE` | `immediate_schedule` の時間帯・間隔一致時のみ |
| 今週決算 | `scripts/run_earnings_job.py --job weekly` | `notify_timing=AT_21` | 常に実行（来週決算を抽出） |
| 明日決算 | `scripts/run_earnings_job.py --job tomorrow` | `notify_timing=AT_21` | 常に実行（翌日決算を抽出） |
| IR通知 | `scripts/run_intelligence_job.py --intel-source ir_only` | `IMMEDIATE/AT_21`（`--execution-mode`準拠） | 常に実行 |
| Grok SNS通知 | `scripts/run_intelligence_job.py --intel-source grok_only --respect-grok-schedule` | `IMMEDIATE/AT_21`（`--execution-mode`準拠） | `grok_sns.enabled=true` かつ JST定時一致時のみ |
| 基礎調査（月次） | `scripts/run_baseline_research_job.py` | なし（委員会評価入力データ更新） | JSTで毎月1日かつ `baseline_monthly_scheduled_time` 一致時のみ |
| 増分バックフィル | `scripts/run_incremental_backfill_job.py` | なし（補完処理） | 常に実行 |
| 技術日次 | `scripts/run_technical_daily_job.py` | 技術アラート（Discord） | 常に実行 |
| 技術全件再同期 | `scripts/run_technical_full_refresh_job.py` | なし（通知抑止で再同期のみ実行） | 常に実行 |

```bash
PYTHONPATH=src python scripts/run_daily_job.py
```

- Firestore `watchlist` を読み込み、日次パイプラインを実行する。
- 実行結果は `daily_metrics` / `metric_medians` / `signal_state` / `notification_log` に保存される。
- `--stdout` 未指定時は `--discord-webhook-url` または `DISCORD_WEBHOOK_URL_DAILY`（fallback: `DISCORD_WEBHOOK_URL`）が必要。
- `JQUANTS_API_KEY` または `--jquants-api-key` を指定した場合、市場データ取得で `J-Quants v2` を最優先で試行し、その後に `株探 → Yahoo!ファイナンス` へフォールバックする。
- `--execution-mode daily|at_21|all` で通知タイミング対象を選択できる（既定: `daily`）。
  - `daily`: `notify_timing=IMMEDIATE` の銘柄のみ
  - `at_21`: `notify_timing=AT_21` の銘柄のみ
  - `all`: 両方
- 委員会評価通知は既定で有効。`global_settings/runtime.committee_daily_scheduled_time`（JST `HH:MM`）と一致した時刻のみ実行される。
- 委員会評価を停止する場合のみ `--disable-committee` を指定する。
- 時刻一致を無視して委員会評価も同時実行する場合は `--ignore-committee-schedule` を指定する（手動再実行用途）。
- 標準出力のJSONは `processed` / `sent` / `skipped` / `errors` を返す。
- 通知条件（割安/データ不明/常時通知ON時の状況通知）に一致しなければ `sent=0` でも正常（ジョブ成功）である。
- クールダウン時間は `global_settings/runtime.cooldown_hours` があればそれを優先し、未設定時は `COOLDOWN_HOURS` を使用する。

stdout送信を明示する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --stdout
```

21時向け銘柄（`notify_timing=AT_21`）だけ実行する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --execution-mode at_21 --discord-webhook-url <DISCORD_WEBHOOK_URL_DAILY>
```

委員会評価を時刻条件を無視して実行する場合:

```bash
PYTHONPATH=src python scripts/run_daily_job.py --ignore-committee-schedule --discord-webhook-url <DISCORD_WEBHOOK_URL_DAILY>
```

IMMEDIATEの寄り付き帯/引け帯ジョブを実行する場合:

```bash
PYTHONPATH=src python scripts/run_immediate_window_job.py --window open --discord-webhook-url <DISCORD_WEBHOOK_URL_DAILY>
PYTHONPATH=src python scripts/run_immediate_window_job.py --window close --discord-webhook-url <DISCORD_WEBHOOK_URL_DAILY>
```

- `global_settings/runtime.immediate_schedule` の時間帯・間隔に一致した時刻のみ実処理する。
- 帯外や間隔未一致の時刻は `processed=0 sent=0 skipped=0 errors=0` を返して正常終了する。

価格・需給テクニカルの日次ジョブを実行する場合:

```bash
PYTHONPATH=src python scripts/run_technical_daily_job.py --discord-webhook-url <DISCORD_WEBHOOK_URL_TECHNICAL>
PYTHONPATH=src python scripts/run_technical_daily_job.py --stdout
```

- `watchlist.is_active=true` の銘柄を対象に `price_bars_daily` 同期、`technical_indicators_daily` 再計算、技術アラート通知をまとめて実行する。
- 実行結果は `price_bars_daily` / `technical_indicators_daily` / `technical_sync_state` / `technical_alert_state` / `notification_log` に反映される。
- 標準出力JSONは `processed_tickers` / `sent_notifications` / `skipped_notifications` / `errors` を返す。
- `--stdout` 未指定時は `--discord-webhook-url` または `DISCORD_WEBHOOK_URL_TECHNICAL`（fallback: `DISCORD_WEBHOOK_URL_DAILY` -> `DISCORD_WEBHOOK_URL`）が必要。

価格・需給テクニカルの全件再同期を実行する場合:

```bash
PYTHONPATH=src python scripts/run_technical_full_refresh_job.py --stdout
PYTHONPATH=src python scripts/run_technical_full_refresh_job.py --tickers 6501:TSE --stdout
```

- `technical_sync_state` を参照せず、保存可能期間全体を再取得・再計算する。
- `run_technical_full_refresh_job.py` は内部で `full_refresh=true` と `skip_alerts=true` を固定する。
- 分割・併合後の再調整吸収や障害復旧では、まず全件再同期でデータ整合性を戻し、その後に通常の `technical_daily` を再実行する。

### 4.2 設定の優先順位（実装準拠）

1. `global_settings/runtime`（管理画面 `/ops` から更新）
2. `.env` / 環境変数
3. コード既定値

主な反映先:

- `run_daily_job.py` / `run_earnings_job.py`:
  - `cooldown_hours` は `global_settings.runtime.cooldown_hours` を優先
- `run_daily_job.py`:
  - `committee_daily_scheduled_time`（JST `HH:MM`）で委員会評価の実行時刻を制御
- `run_immediate_window_job.py`:
  - `cooldown_hours` と `immediate_schedule.*` を `global_settings.runtime` から解決
- `run_baseline_research_job.py`:
  - `baseline_monthly_scheduled_time`（JST `HH:MM`）で月次更新の実行時刻を制御
  - `EDINET_API_KEY` / `ESTAT_APP_ID` / `ESTAT_CPI_STATS_DATA_ID` 設定時は基礎調査に一次情報エンリッチを追加
  - e-Stat の最新値欠損時は `raw.estat.missing_reason=latest_value_not_found` と `summary.macro_note` を保存して可視化
- `run_intelligence_job.py`:
  - `cooldown_hours`
  - `intel_notification_max_age_days`
  - `grok_sns.enabled/scheduled_time/per_ticker_cooldown_hours/prompt_template`
  - 以上を `global_settings.runtime` 優先で解決
- `run_backfill_daily_metrics.py` / `run_incremental_backfill_job.py`:
  - `JQUANTS_API_KEY` 等の環境変数ベースで動作（`global_settings` は参照しない）

定期実行（Cloud Run Jobs + Scheduler）での既定構成:

- `kabu-immediate-open` <- `sc-kabu-immediate-open`（平日8:00-11:59 毎分起動、設定一致時のみ実処理）
- `kabu-immediate-close` <- `sc-kabu-immediate-close`（平日13:00-16:59 毎分起動、設定一致時のみ実処理）
- `kabu-daily` <- `sc-kabu-daily`（平日18:00 JST）
- `kabu-daily-at21` <- `sc-kabu-daily-at21`（平日21:05 JST）
- `kabu-intelligence` <- `sc-kabu-intelligence`（平日21:05 JST、IR中心）
- `kabu-grok` <- `sc-kabu-grok`（毎分起動、管理画面の Grok定時取得時刻と一致した分のみ実処理）
- `kabu-baseline-research` <- `sc-kabu-baseline-research`（毎月1日 18:00 JST）
- `kabu-backfill-incremental` <- `sc-kabu-backfill-incremental`（土曜21:15 JST）
- `kabu-technical-daily`（Cloud Run Job のみ作成。定期スケジューラは未付与のため `/ops` または手動実行で使用）
- `kabu-technical-full-refresh`（Cloud Run Job のみ作成。障害復旧・再調整吸収用）
- `kabu-earnings-weekly` <- `sc-kabu-earnings-weekly`（土曜21:00 JST）
- `kabu-earnings-tomorrow` <- `sc-kabu-earnings-tomorrow`（毎日21:00 JST）

補足:
- `kabu-backfill-incremental` は `J-Quants APIキー` の Secret（既定: `jquants-api-key`）が利用可能な場合のみ作成される。
- `kabu-grok` は `GROK_API_KEY` の Secret（既定: `grok-api-key`）が利用可能な場合のみ作成される。

確認コマンド:

```bash
gcloud run jobs executions list --job=kabu-immediate-open --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud run jobs executions list --job=kabu-immediate-close --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud run jobs executions list --job=kabu-daily --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud run jobs executions list --job=kabu-daily-at21 --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud run jobs executions list --job=kabu-intelligence --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud run jobs executions list --job=kabu-grok --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud run jobs executions list --job=kabu-technical-daily --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud run jobs executions list --job=kabu-technical-full-refresh --region=asia-northeast1 --project=<GCP_PROJECT_ID>
gcloud scheduler jobs list --location=asia-northeast1 --project=<GCP_PROJECT_ID>
```

## 5. Discord疎通

```bash
PYTHONPATH=src python scripts/send_discord_test_notification.py --webhook-url <DISCORD_WEBHOOK_URL>
```

または:

```bash
export DISCORD_WEBHOOK_URL=<DISCORD_WEBHOOK_URL>
PYTHONPATH=src python scripts/send_discord_test_notification.py
```

## 6. 決算通知ジョブ（Issue 15）

```bash
PYTHONPATH=src python scripts/run_earnings_job.py --job weekly --discord-webhook-url <DISCORD_WEBHOOK_URL_EARNINGS>
PYTHONPATH=src python scripts/run_earnings_job.py --job tomorrow --discord-webhook-url <DISCORD_WEBHOOK_URL_EARNINGS>
```

- `weekly`: 土曜21時（JST）想定。来週決算を `今週決算` として通知。
- `tomorrow`: 毎日21時（JST）想定。翌日決算を `明日決算` として通知。
- `FIRESTORE_PROJECT_ID` と `DISCORD_WEBHOOK_URL_EARNINGS`（fallback: `DISCORD_WEBHOOK_URL`）を利用する。

## 7. IR/SNS/AI通知ジョブ

```bash
PYTHONPATH=src python scripts/run_intelligence_job.py --intel-source ir_only --discord-webhook-url-ir <DISCORD_WEBHOOK_URL_INTELLIGENCE_IR>
PYTHONPATH=src python scripts/run_intelligence_job.py --intel-source grok_only --respect-grok-schedule --discord-webhook-url-sns <DISCORD_WEBHOOK_URL_INTELLIGENCE_SNS>
```

- `【AI注目】` はウォッチリスト銘柄に対して常時送信を試行（AI失敗時は `IR更新` / `SNS注目` のみ継続）。
- SNS監視（Grok）には `GROK_API_KEY` が必要（未設定時は `【データ不明】` 通知）。
- モデルは `GROK_MODEL_FAST` を優先し、抽出失敗時は `GROK_MODEL_REASONING` へフォールバック。
- `--intel-source ir_only|grok_only|all` でIR/Grokの実行範囲を分離できる。
- `--intel-source all` 指定時も内部では `ir_only` と `grok_only` を別パイプラインで実行し、結果を集約する。
- `--intel-source grok_only --respect-grok-schedule` 指定時は `GROK_SNS_ENABLED=true` かつ実行時刻（JST）が `GROK_SNS_SCHEDULED_TIME` と一致した分のみ処理する。
- `GROK_SNS_PER_TICKER_COOLDOWN_HOURS` の間は、同一銘柄の `SNS注目` 通知が直近にある場合は再取得をスキップする。
- AI要約は `Vertex AI Gemini` を利用し、`VERTEX_AI_LOCATION` / `VERTEX_AI_MODEL` で変更できる。
- IRリンク先の HTML/PDF 本文を取得し、本文テキストを要約対象として扱う。
- IR通知は銘柄ごとの初回実行時に既読化のみを行い、通知は送信しない（Grok SNSは初回から通知対象）。
- IR/SNS通知対象期間は `INTEL_NOTIFICATION_MAX_AGE_DAYS`（既定30日）または管理画面 `/ops` の全体設定 `intel_notification_max_age_days` で変更できる。
- `--execution-mode daily|at_21` で通知時間フィルタを指定可能。

Webhook分割（任意）:

- 日次/IMMEDIATE: `DISCORD_WEBHOOK_URL_DAILY`
- 技術アラート: `DISCORD_WEBHOOK_URL_TECHNICAL`
- 決算: `DISCORD_WEBHOOK_URL_EARNINGS`
- IR: `DISCORD_WEBHOOK_URL_INTELLIGENCE_IR`
- SNS/AI: `DISCORD_WEBHOOK_URL_INTELLIGENCE_SNS`
- IR/SNS共通fallback: `DISCORD_WEBHOOK_URL_INTELLIGENCE`
- いずれも未設定時は `DISCORD_WEBHOOK_URL` をフォールバック利用

## 8. マイグレーション

```bash
PYTHONPATH=src python scripts/migrate_firestore_v0001.py --project-id <GCP_PROJECT_ID>
```

## 9. デプロイ前機械チェック（W12）

Hosting / Cloud Run へ反映する前に、ローカルで事前チェックだけ実行する。

```bash
cd /Users/ishidafuu/Documents/repository/kabu_per_bot
bash scripts/preflight_deploy_check.sh
```

- `python/node/npm/git` の存在確認を行う。
- `web` の `npm run build` 成功を確認する。
- 主要環境変数（`.env`, `web/.env.local`）の未設定は `WARN` 表示で通知する。
- 終了コード `0`: 事前チェック通過、`1`: 失敗あり（要修正）。

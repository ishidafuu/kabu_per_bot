# 株式監視BOT MVP仕様分解（受け入れ基準つき）

## 1. スコープ（MVP）

MVPで実装する対象は以下とする。

1. ウォッチリスト管理（最大100銘柄、PER/PSR切替、通知先設定、追加/削除履歴）
2. PER/PSR日次計算（終値ベース、1Y/3M/1W中央値、under判定、連続日数）
3. 通知（PER/PSR、今週決算、明日決算、データ不明）
4. Discord/LINEへの配信
5. クールダウン（同条件2時間抑制）

MVP外（第2段階）:

1. IR/SNS監視
2. AI注目通知（要約/根拠/分類）

## 2. 主要ルール（確定事項）

1. 対象は日本株のみ（ETF/REIT除外）
2. ティッカーは `1234:TSE` 形式で統一
3. PERは「会社予想EPS（今期）」を使用
4. 期間中央値は営業日ベースで `1W=5 / 3M=63 / 1Y=252`（設定変更可能）
5. 強通知は `under_1y && under_3m && under_1w`
6. 通知カテゴリ:
   `PER割安 / 超PER割安 / PSR割安 / 超PSR割安 / 今週決算 / 明日決算 / データ不明`

## 3. 受け入れ基準（Acceptance Criteria）

### 3.1 ウォッチリスト管理

- Given: 未登録銘柄がある
  When: ティッカーを追加する
  Then: 銘柄情報が保存され、監視方式（PER/PSR）と通知先設定が保持される

- Given: 監視銘柄が登録済み
  When: 銘柄を削除する
  Then: 監視対象から除外され、削除履歴（日時・操作・理由）が残る

- Given: 銘柄数が100件
  When: 101件目を追加する
  Then: 追加を拒否し、上限超過エラーを返す

### 3.2 指標計算（PER/PSR）

- Given: 終値と会社予想EPS（今期）が取得できる
  When: 日次更新バッチを実行する
  Then: `PER = close / eps_forecast` を保存する

- Given: EPSが0以下または欠損
  When: PER計算を試行する
  Then: PERを未定義として扱い、PSR監視銘柄はPSR計算へ進む

- Given: 指標時系列データがある
  When: 日次更新バッチを実行する
  Then: 1W/3M/1Yの中央値を再計算し保存する

### 3.3 under判定・連続日数

- Given: 当日指標値と中央値がある
  When: 判定処理を行う
  Then: `under_1y / under_3m / under_1w` を算出し、通常通知3パターンと強通知を決定する

- Given: 前営業日も同一条件でunderだった
  When: 当日も同一条件でunder
  Then: 連続日数を+1する

- Given: 前営業日にunder条件を満たしていた
  When: 当日条件を満たさない
  Then: 連続日数をリセットする

### 3.4 通知（重複抑制込み）

- Given: 同一銘柄・同一カテゴリ・同一条件の通知履歴が2時間以内にある
  When: 同一通知を再評価する
  Then: 再送しない

- Given: 通常通知が出ている状態
  When: 強通知条件へ遷移する
  Then: クールダウン中でも即時通知する

- Given: 決算日程データがある
  When: 土曜21:00ジョブを実行する
  Then: 来週の決算を `今週決算` として通知する

- Given: 決算日程データがある
  When: 毎日21:00ジョブを実行する
  Then: 翌日の決算を `明日決算` として通知する

### 3.5 欠損通知

- Given: EPS/売上/決算日時のいずれかが欠損
  When: 日次更新または通知生成を行う
  Then: `【データ不明】` 通知を生成し、欠損項目名を本文に含める

## 4. データモデル（初版）

最低限のテーブル（または同等の永続化構造）を定義する。

1. `watchlist`
   `ticker, name, metric_type(PER|PSR), notify_channel, notify_timing, ai_enabled, is_active`
2. `watchlist_history`
   `id, ticker, action(ADD|REMOVE), reason, acted_at`
3. `daily_metrics`
   `ticker, trade_date, close_price, eps_forecast, sales_forecast, per_value, psr_value`
4. `metric_medians`
   `ticker, trade_date, median_1w, median_3m, median_1y`
5. `signal_state`
   `ticker, trade_date, under_1w, under_3m, under_1y, combo, is_strong, streak_days`
6. `earnings_calendar`
   `ticker, earnings_date, earnings_time, quarter, source, fetched_at`
7. `notification_log`
   `id, ticker, category, condition_key, sent_at, channel, payload_hash`

## 5. 実装順（推奨）

1. モデル実装（watchlist, daily_metrics, notification_log）
2. 日次計算バッチ（PER/PSR算出、中央値、under判定）
3. 通知判定（クールダウン、通常/強遷移）
4. 決算通知ジョブ（土曜21時/毎日21時）
5. Discord/LINE配信アダプタ
6. 欠損通知と運用ログ

## 6. 仕様の未確定ポイント（次に決める項目）

1. 通知時間「21時」はJST固定か、ユーザータイムゾーン追従か
2. PER未定義時の振る舞い（PSRへ自動フォールバック or その日は通知なし）
3. 四季報online取得失敗時のフォールバック優先順の固定値
4. 決算「来週」の範囲（週の起点を月曜固定とするか）
5. LINE通知の実装方式（Messaging API / Notify代替）

## 7. 暫定デフォルト（先行実装用）

合意が取れるまで、以下の暫定値で実装を進める。

1. 通知時刻はJST固定
2. PER未定義日は、PER監視銘柄でも `データ不明` 通知を優先（自動PSR切替はしない）
3. データ取得フォールバック順は `四季報online → 株探 → Yahoo!ファイナンス`
4. 「来週」は月曜開始〜日曜終了の暦週で判定
5. LINEはMessaging API前提で実装（Notifyは非推奨扱い）

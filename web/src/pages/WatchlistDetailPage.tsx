import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { AppLayout } from '../components/AppLayout';
import { createWatchlistClient } from '../lib/api';
import { toUserMessage } from '../lib/api/errors';
import { appConfig } from '../lib/config';
import type {
  TechnicalAlertOperator,
  TechnicalAlertRule,
  TechnicalAlertRuleCreateInput,
  TechnicalAlertRuleUpdateInput,
  WatchlistDetailResponse,
} from '../types/watchlistDetail';

const dateTimeFormatter = new Intl.DateTimeFormat('ja-JP', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZone: 'Asia/Tokyo',
});

const TECHNICAL_FIELD_OPTIONS = [
  { key: 'close_vs_ma25', label: '終値-25日線乖離', valueType: 'number' },
  { key: 'close_vs_ma75', label: '終値-75日線乖離', valueType: 'number' },
  { key: 'close_vs_ma200', label: '終値-200日線乖離', valueType: 'number' },
  { key: 'volume_ratio', label: '出来高倍率', valueType: 'number' },
  { key: 'turnover_ratio', label: '売買代金倍率', valueType: 'number' },
  { key: 'atr_pct_14', label: 'ATR% (14日)', valueType: 'number' },
  { key: 'volatility_20d', label: '20日ボラティリティ', valueType: 'number' },
  { key: 'new_high_20d', label: '20日高値更新', valueType: 'boolean' },
  { key: 'new_high_52w', label: '52週高値更新', valueType: 'boolean' },
  { key: 'cross_up_ma25', label: '25日線上抜け', valueType: 'boolean' },
  { key: 'cross_down_ma25', label: '25日線下抜け', valueType: 'boolean' },
  { key: 'trend_mid_up', label: '中期上昇トレンド', valueType: 'boolean' },
  { key: 'perfect_order_flag', label: 'パーフェクトオーダー', valueType: 'boolean' },
] as const;

const OPERATOR_OPTIONS: Array<{ value: TechnicalAlertOperator; label: string }> = [
  { value: 'IS_TRUE', label: 'TRUE' },
  { value: 'IS_FALSE', label: 'FALSE' },
  { value: 'GTE', label: '>=' },
  { value: 'LTE', label: '<=' },
  { value: 'BETWEEN', label: '範囲内' },
  { value: 'OUTSIDE', label: '範囲外' },
];

const BOOLEAN_OPERATOR_OPTIONS = OPERATOR_OPTIONS.filter((row) => row.value === 'IS_TRUE' || row.value === 'IS_FALSE');
const NUMERIC_OPERATOR_OPTIONS = OPERATOR_OPTIONS.filter((row) => row.value !== 'IS_TRUE' && row.value !== 'IS_FALSE');

const formatDateTime = (value?: string | null): string => {
  if (!value) {
    return '-';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return dateTimeFormatter.format(date);
};

const formatNumber = (value?: number | null): string => {
  if (value == null) {
    return '-';
  }
  return value.toFixed(2);
};

const formatTechnicalValue = (value: string | number | boolean | null | undefined): string => {
  if (value == null) {
    return '-';
  }
  if (typeof value === 'boolean') {
    return value ? 'TRUE' : 'FALSE';
  }
  if (typeof value === 'number') {
    return value.toFixed(2);
  }
  return value;
};

const formatThreshold = (rule: TechnicalAlertRule): string => {
  if (rule.operator === 'IS_TRUE') {
    return 'TRUE';
  }
  if (rule.operator === 'IS_FALSE') {
    return 'FALSE';
  }
  if (rule.operator === 'GTE') {
    return `>= ${formatNumber(rule.threshold_value)}`;
  }
  if (rule.operator === 'LTE') {
    return `<= ${formatNumber(rule.threshold_value)}`;
  }
  if (rule.operator === 'BETWEEN') {
    return `${formatNumber(rule.threshold_value)} - ${formatNumber(rule.threshold_upper)}`;
  }
  return `< ${formatNumber(rule.threshold_value)} または > ${formatNumber(rule.threshold_upper)}`;
};

const formatEarnings = (date?: string | null, time?: string | null): string => {
  if (!date) {
    return '-';
  }
  return `${date} ${time ?? '未定'}`;
};

const formatEarningsDays = (days?: number | null): string => {
  if (days == null) {
    return '-';
  }
  if (days <= 0) {
    return '当日';
  }
  return `${days}日`;
};

const isBooleanOperator = (operator: TechnicalAlertOperator): boolean => {
  return operator === 'IS_TRUE' || operator === 'IS_FALSE';
};

const needsUpperThreshold = (operator: TechnicalAlertOperator): boolean => {
  return operator === 'BETWEEN' || operator === 'OUTSIDE';
};

const getTechnicalFieldOption = (fieldKey: string) => {
  return TECHNICAL_FIELD_OPTIONS.find((row) => row.key === fieldKey) ?? TECHNICAL_FIELD_OPTIONS[0];
};

const isBooleanFieldKey = (fieldKey: string): boolean => {
  return getTechnicalFieldOption(fieldKey).valueType === 'boolean';
};

const getOperatorOptions = (fieldKey: string): Array<{ value: TechnicalAlertOperator; label: string }> => {
  return isBooleanFieldKey(fieldKey) ? BOOLEAN_OPERATOR_OPTIONS : NUMERIC_OPERATOR_OPTIONS;
};

type RuleFormState = {
  rule_name: string;
  field_key: string;
  operator: TechnicalAlertOperator;
  threshold_value: string;
  threshold_upper: string;
  note: string;
  is_active: boolean;
};

const buildEmptyRuleForm = (): RuleFormState => ({
  rule_name: '',
  field_key: TECHNICAL_FIELD_OPTIONS[0].key,
  operator: 'GTE',
  threshold_value: '0',
  threshold_upper: '',
  note: '',
  is_active: true,
});

const parseOptionalNumber = (value: string): number | null => {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  if (Number.isNaN(parsed)) {
    throw new Error('しきい値は数値で入力してください。');
  }
  return parsed;
};

const toRulePayload = (form: RuleFormState): TechnicalAlertRuleCreateInput => {
  const payload: TechnicalAlertRuleCreateInput = {
    rule_name: form.rule_name.trim(),
    field_key: form.field_key,
    operator: form.operator,
    is_active: form.is_active,
    note: form.note.trim() || null,
  };
  if (!payload.rule_name) {
    throw new Error('ルール名を入力してください。');
  }
  if (!isBooleanOperator(form.operator)) {
    payload.threshold_value = parseOptionalNumber(form.threshold_value);
    if (payload.threshold_value == null) {
      throw new Error('しきい値を入力してください。');
    }
  }
  if (needsUpperThreshold(form.operator)) {
    payload.threshold_upper = parseOptionalNumber(form.threshold_upper);
    if (payload.threshold_upper == null) {
      throw new Error('上限値を入力してください。');
    }
  }
  return payload;
};

const technicalHighlightKeys = [
  'close_vs_ma25',
  'close_vs_ma75',
  'close_vs_ma200',
  'volume_ratio',
  'turnover_ratio',
  'atr_pct_14',
  'volatility_20d',
  'cross_up_ma25',
  'new_high_20d',
] as const;

export const WatchlistDetailPage = () => {
  const { ticker } = useParams();
  const { getIdToken } = useAuth();
  const client = useMemo(() => createWatchlistClient({ getToken: getIdToken }), [getIdToken]);

  const [detail, setDetail] = useState<WatchlistDetailResponse | null>(null);
  const [categoryInput, setCategoryInput] = useState('');
  const [category, setCategory] = useState('');
  const [strongOnly, setStrongOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null);
  const [ruleForm, setRuleForm] = useState<RuleFormState>(buildEmptyRuleForm);
  const [ruleMessage, setRuleMessage] = useState('');
  const [ruleError, setRuleError] = useState('');
  const [isSavingRule, setIsSavingRule] = useState(false);
  const [initialFetchMessage, setInitialFetchMessage] = useState('');
  const [initialFetchError, setInitialFetchError] = useState('');
  const [isRequestingInitialFetch, setIsRequestingInitialFetch] = useState(false);
  const limit = appConfig.pageSize;
  const historyLimit = 10;
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const currentFieldOption = getTechnicalFieldOption(ruleForm.field_key);
  const currentOperatorOptions = getOperatorOptions(ruleForm.field_key);
  const currentFieldIsBoolean = currentFieldOption.valueType === 'boolean';

  const fetchDetail = useCallback(async (): Promise<void> => {
    if (!ticker) {
      setLoadError('ticker が不正です。');
      return;
    }
    setIsLoading(true);
    setLoadError('');

    try {
      const response = await client.getDetail(ticker, {
        category: category || undefined,
        strong_only: strongOnly || undefined,
        limit,
        offset,
        history_limit: historyLimit,
        history_offset: historyOffset,
      });
      setDetail(response);
    } catch (error) {
      setLoadError(toUserMessage(error));
      setDetail(null);
    } finally {
      setIsLoading(false);
    }
  }, [category, client, historyLimit, historyOffset, limit, offset, strongOnly, ticker]);

  useEffect(() => {
    void fetchDetail();
  }, [fetchDetail]);

  const handleSearch = (): void => {
    setOffset(0);
    setCategory(categoryInput.trim());
  };

  const resetRuleForm = (): void => {
    setEditingRuleId(null);
    setRuleForm(buildEmptyRuleForm());
  };

  const startEditRule = (rule: TechnicalAlertRule): void => {
    setEditingRuleId(rule.rule_id);
    setRuleForm({
      rule_name: rule.rule_name,
      field_key: rule.field_key,
      operator: rule.operator,
      threshold_value: rule.threshold_value != null ? String(rule.threshold_value) : '',
      threshold_upper: rule.threshold_upper != null ? String(rule.threshold_upper) : '',
      note: rule.note ?? '',
      is_active: rule.is_active,
    });
    setRuleMessage('');
    setRuleError('');
  };

  const handleSubmitRule = async (): Promise<void> => {
    if (!ticker) {
      return;
    }
    setIsSavingRule(true);
    setRuleMessage('');
    setRuleError('');
    try {
      const payload = toRulePayload(ruleForm);
      if (editingRuleId) {
        const updatePayload: TechnicalAlertRuleUpdateInput = payload;
        await client.updateTechnicalAlertRule(ticker, editingRuleId, updatePayload);
        setRuleMessage('技術アラートルールを更新しました。');
      } else {
        await client.createTechnicalAlertRule(ticker, payload);
        setRuleMessage('技術アラートルールを追加しました。');
      }
      resetRuleForm();
      await fetchDetail();
    } catch (error) {
      if (error instanceof Error) {
        setRuleError(error.message);
      } else {
        setRuleError(toUserMessage(error));
      }
    } finally {
      setIsSavingRule(false);
    }
  };

  const toggleRuleActive = async (rule: TechnicalAlertRule): Promise<void> => {
    if (!ticker) {
      return;
    }
    setIsSavingRule(true);
    setRuleMessage('');
    setRuleError('');
    try {
      await client.updateTechnicalAlertRule(ticker, rule.rule_id, {
        is_active: !rule.is_active,
      });
      setRuleMessage(rule.is_active ? '技術アラートルールを無効化しました。' : '技術アラートルールを有効化しました。');
      await fetchDetail();
    } catch (error) {
      setRuleError(toUserMessage(error));
    } finally {
      setIsSavingRule(false);
    }
  };

  const notificationTotal = detail?.notifications.total ?? 0;
  const historyTotal = detail?.history.total ?? 0;
  const canGoNotificationPrev = offset > 0;
  const canGoNotificationNext = offset + limit < notificationTotal;
  const canGoHistoryPrev = historyOffset > 0;
  const canGoHistoryNext = historyOffset + historyLimit < historyTotal;

  const item = detail?.item;
  const summary = detail?.summary;
  const technicalRules = detail?.technical_rules.items ?? [];
  const latestTechnical = detail?.latest_technical;
  const latestTechnicalRows = technicalHighlightKeys
    .map((key) => ({
      key,
      label: TECHNICAL_FIELD_OPTIONS.find((row) => row.key === key)?.label ?? key,
      value: latestTechnical?.values[key],
    }))
    .filter((row) => row.value != null);

  const requestTechnicalInitialFetch = async (): Promise<void> => {
    if (!ticker) {
      return;
    }
    setIsRequestingInitialFetch(true);
    setInitialFetchMessage('');
    setInitialFetchError('');
    try {
      const response = await client.requestTechnicalInitialFetch(ticker);
      setInitialFetchMessage(
        `過去データ取得を受け付けました。job=${response.job_label} execution=${response.execution_name}`,
      );
      await fetchDetail();
    } catch (error) {
      setInitialFetchError(toUserMessage(error));
    } finally {
      setIsRequestingInitialFetch(false);
    }
  };

  return (
    <AppLayout
      title={item ? `銘柄詳細: ${item.ticker}` : '銘柄詳細'}
      subtitle={item ? `${item.name} の通知履歴と現況を確認できます。` : '通知履歴と現況を確認できます。'}
    >
      <section className="panel controls-panel">
        <div className="search-row detail-filter-row">
          <input
            type="search"
            placeholder="通知カテゴリで絞り込み（例: 超PER割安）"
            value={categoryInput}
            onChange={(event) => {
              setCategoryInput(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                handleSearch();
              }
            }}
          />
          <label className="inline-checkbox detail-inline-checkbox">
            <input
              type="checkbox"
              checked={strongOnly}
              onChange={(event) => {
                setOffset(0);
                setStrongOnly(event.target.checked);
              }}
            />
            強通知のみ
          </label>
          <button type="button" className="secondary" onClick={handleSearch}>
            絞り込み
          </button>
          <Link className="nav-link detail-back-link" to="/watchlist">
            一覧へ戻る
          </Link>
        </div>
      </section>

      {loadError && <p className="error-text">{loadError}</p>}

      <section className="detail-grid">
        <article className="panel detail-card">
          <div className="panel-header">
            <h2>通知サマリ</h2>
          </div>
          <div className="detail-summary-grid">
            <div className="watchlist-meta-item">
              <span className="muted">最終通知</span>
              <strong>{formatDateTime(summary?.last_notification_at)}</strong>
              <small>{summary?.last_notification_category ?? '-'}</small>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">直近7日通知件数</span>
              <strong>{summary?.notification_count_7d ?? 0}</strong>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">直近30日強通知件数</span>
              <strong>{summary?.strong_notification_count_30d ?? 0}</strong>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">直近30日データ不明件数</span>
              <strong>{summary?.data_unknown_count_30d ?? 0}</strong>
            </div>
          </div>
        </article>

        <article className="panel detail-card">
          <div className="panel-header">
            <h2>現在の判定</h2>
          </div>
          <div className="detail-status-grid">
            <div className="watchlist-meta-item">
              <span className="muted">監視方式</span>
              <strong>{item?.metric_type ?? '-'}</strong>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">通知タイミング</span>
              <strong>{item?.notify_timing ?? '-'}</strong>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">優先度</span>
              <strong>{item?.priority ?? '-'}</strong>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">現在値</span>
              <strong>{formatNumber(item?.current_metric_value)}</strong>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">中央値 (1W / 3M / 1Y)</span>
              <strong>
                {`${formatNumber(item?.median_1w)} / ${formatNumber(item?.median_3m)} / ${formatNumber(item?.median_1y)}`}
              </strong>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">シグナル</span>
              <strong>{item?.signal_category ? `${item.signal_category} ${item.signal_combo ?? ''}` : '-'}</strong>
              <small>{item?.signal_streak_days ? `${item.signal_streak_days}日連続` : '-'}</small>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">次回決算</span>
              <strong>{formatEarnings(item?.next_earnings_date, item?.next_earnings_time)}</strong>
            </div>
            <div className="watchlist-meta-item">
              <span className="muted">決算まで</span>
              <strong>{formatEarningsDays(item?.next_earnings_days)}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="detail-grid">
        <article className="panel detail-card">
          <div className="panel-header">
            <h2>最新テクニカル</h2>
            <span className="muted">{latestTechnical ? `${latestTechnical.trade_date} 基準` : '未計算'}</span>
          </div>
          {initialFetchMessage && <p className="success-text">{initialFetchMessage}</p>}
          {initialFetchError && <p className="error-text">{initialFetchError}</p>}
          {!latestTechnical && (
            <div className="technical-fetch-actions">
              <p className="empty-note">過去データが未取得のため、まだテクニカル指標を表示できません。</p>
              <button
                type="button"
                disabled={isRequestingInitialFetch}
                onClick={() => {
                  void requestTechnicalInitialFetch();
                }}
              >
                {isRequestingInitialFetch ? '取得依頼中...' : '過去データを一括取得'}
              </button>
            </div>
          )}
          <div className="detail-status-grid">
            {latestTechnicalRows.length === 0 && latestTechnical && (
              <p className="empty-note">最新テクニカル指標はまだ保存されていません。</p>
            )}
            {latestTechnicalRows.map((row) => (
              <div key={row.key} className="watchlist-meta-item technical-meta-item">
                <span className="muted">{row.label}</span>
                <strong>{formatTechnicalValue(row.value)}</strong>
                <small>{row.key}</small>
              </div>
            ))}
            {latestTechnical && (
              <div className="watchlist-meta-item technical-meta-item">
                <span className="muted">計算時刻</span>
                <strong>{formatDateTime(latestTechnical.calculated_at)}</strong>
                <small>schema v{latestTechnical.schema_version}</small>
              </div>
            )}
          </div>
        </article>

        <article className="panel detail-card">
          <div className="panel-header">
            <h2>直近発火履歴</h2>
            <span className="muted">{detail?.technical_alert_history.total ?? 0}件</span>
          </div>
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>送信日時</th>
                  <th>条件キー</th>
                  <th>本文</th>
                </tr>
              </thead>
              <tbody>
                {(detail?.technical_alert_history.items.length ?? 0) === 0 && (
                  <tr>
                    <td colSpan={3} className="empty-cell">
                      技術アラートの発火履歴はありません。
                    </td>
                  </tr>
                )}
                {detail?.technical_alert_history.items.map((row) => (
                  <tr key={row.entry_id}>
                    <td>{formatDateTime(row.sent_at)}</td>
                    <td>{row.condition_key}</td>
                    <td className="detail-body-cell">{row.body ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <section className="panel detail-rule-panel">
        <div className="panel-header">
          <h2>技術アラートルール</h2>
          <span className="muted">{detail?.technical_rules.total ?? 0}件</span>
        </div>
        {ruleMessage && <p className="success-text">{ruleMessage}</p>}
        {ruleError && <p className="error-text">{ruleError}</p>}
        <div className="technical-rule-list">
          {technicalRules.length === 0 && <p className="empty-note">ルールはまだ登録されていません。</p>}
          {technicalRules.map((rule) => (
            <article
              key={rule.rule_id}
              className={`technical-rule-card${rule.is_active ? '' : ' is-inactive'}`}
            >
              <div className="technical-rule-card-head">
                <div>
                  <h3>{rule.rule_name}</h3>
                  <p className="muted">
                    {rule.field_key} / {formatThreshold(rule)}
                  </p>
                </div>
                <span className={`technical-rule-badge${rule.is_active ? ' is-active' : ''}`}>
                  {rule.is_active ? '有効' : '無効'}
                </span>
              </div>
              <p className="technical-rule-note">{rule.note ?? 'メモなし'}</p>
              <div className="technical-rule-card-foot">
                <span className="muted">更新: {formatDateTime(rule.updated_at)}</span>
                <div className="technical-rule-actions">
                  <button type="button" className="secondary" onClick={() => startEditRule(rule)}>
                    編集
                  </button>
                  <button
                    type="button"
                    className="secondary"
                    disabled={isSavingRule}
                    onClick={() => {
                      void toggleRuleActive(rule);
                    }}
                  >
                    {rule.is_active ? '無効化' : '有効化'}
                  </button>
                </div>
              </div>
            </article>
          ))}
        </div>

        <div className="technical-rule-editor">
          <div className="panel-header">
            <h3>{editingRuleId ? 'ルールを編集' : 'ルールを追加'}</h3>
          </div>
          <div className="technical-rule-form-grid">
            <label>
              ルール名
              <input
                value={ruleForm.rule_name}
                onChange={(event) => {
                  setRuleForm((current) => ({ ...current, rule_name: event.target.value }));
                }}
              />
            </label>
            <label>
              指標
              <select
                value={ruleForm.field_key}
                onChange={(event) => {
                  const nextFieldKey = event.target.value;
                  const nextFieldIsBoolean = isBooleanFieldKey(nextFieldKey);
                  setRuleForm((current) => ({
                    ...current,
                    field_key: nextFieldKey,
                    operator: nextFieldIsBoolean ? 'IS_TRUE' : isBooleanOperator(current.operator) ? 'GTE' : current.operator,
                    threshold_value: nextFieldIsBoolean ? '' : current.threshold_value || '0',
                    threshold_upper: nextFieldIsBoolean ? '' : current.threshold_upper,
                  }));
                }}
              >
                {TECHNICAL_FIELD_OPTIONS.map((row) => (
                  <option key={row.key} value={row.key}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              判定方法
              <select
                value={ruleForm.operator}
                onChange={(event) => {
                  setRuleForm((current) => ({
                    ...current,
                    operator: event.target.value as TechnicalAlertOperator,
                  }));
                }}
              >
                {currentOperatorOptions.map((row) => (
                  <option key={row.value} value={row.value}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
            {currentFieldIsBoolean && (
              <div className="form-note-block">
                <span className="muted">フラグ項目です。しきい値は不要で、TRUE / FALSE 判定のみ指定できます。</span>
              </div>
            )}
            {!currentFieldIsBoolean && !isBooleanOperator(ruleForm.operator) && (
              <label>
                {needsUpperThreshold(ruleForm.operator) ? '下限値' : '基準値'}
                <input
                  value={ruleForm.threshold_value}
                  onChange={(event) => {
                    setRuleForm((current) => ({ ...current, threshold_value: event.target.value }));
                  }}
                />
              </label>
            )}
            {!currentFieldIsBoolean && needsUpperThreshold(ruleForm.operator) && (
              <label>
                上限値
                <input
                  value={ruleForm.threshold_upper}
                  onChange={(event) => {
                    setRuleForm((current) => ({ ...current, threshold_upper: event.target.value }));
                  }}
                />
              </label>
            )}
            <label className="technical-rule-note-field">
              メモ
              <textarea
                value={ruleForm.note}
                rows={3}
                onChange={(event) => {
                  setRuleForm((current) => ({ ...current, note: event.target.value }));
                }}
              />
            </label>
            <label className="inline-checkbox">
              <input
                type="checkbox"
                checked={ruleForm.is_active}
                onChange={(event) => {
                  setRuleForm((current) => ({ ...current, is_active: event.target.checked }));
                }}
              />
              保存直後から有効にする
            </label>
          </div>
          <div className="technical-rule-actions">
            <button
              type="button"
              disabled={isSavingRule}
              onClick={() => {
                void handleSubmitRule();
              }}
            >
              {editingRuleId ? '更新する' : '追加する'}
            </button>
            {editingRuleId && (
              <button type="button" className="secondary" onClick={resetRuleForm}>
                編集をやめる
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="panel table-panel detail-table-panel">
        <div className="panel-header">
          <h2>通知タイムライン</h2>
        </div>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>送信日時</th>
                <th>カテゴリ</th>
                <th>強通知</th>
                <th>条件キー</th>
                <th>本文</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (detail?.notifications.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={5} className="empty-cell">
                    読み込み中...
                  </td>
                </tr>
              )}
              {!isLoading && (detail?.notifications.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={5} className="empty-cell">
                    該当する通知ログがありません。
                  </td>
                </tr>
              )}
              {detail?.notifications.items.map((row) => (
                <tr key={row.entry_id}>
                  <td>{formatDateTime(row.sent_at)}</td>
                  <td>{row.category}</td>
                  <td>{row.is_strong ? '強' : '通常'}</td>
                  <td>{row.condition_key}</td>
                  <td className="detail-body-cell">{row.body ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination-row">
          <button
            type="button"
            className="secondary"
            disabled={!canGoNotificationPrev || isLoading}
            onClick={() => {
              setOffset((current) => Math.max(0, current - limit));
            }}
          >
            前へ
          </button>
          <span className="muted">
            {notificationTotal === 0
              ? '0 / 0'
              : `${offset + 1}-${Math.min(offset + limit, notificationTotal)} / ${notificationTotal}`}
          </span>
          <button
            type="button"
            className="secondary"
            disabled={!canGoNotificationNext || isLoading}
            onClick={() => {
              setOffset((current) => current + limit);
            }}
          >
            次へ
          </button>
        </div>
      </section>

      <section className="panel table-panel detail-table-panel">
        <div className="panel-header">
          <h2>操作履歴</h2>
        </div>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>日時</th>
                <th>操作</th>
                <th>理由</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && (detail?.history.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={3} className="empty-cell">
                    読み込み中...
                  </td>
                </tr>
              )}
              {!isLoading && (detail?.history.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={3} className="empty-cell">
                    操作履歴はありません。
                  </td>
                </tr>
              )}
              {detail?.history.items.map((row) => (
                <tr key={row.record_id}>
                  <td>{formatDateTime(row.acted_at)}</td>
                  <td>{row.action}</td>
                  <td>{row.reason ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination-row">
          <button
            type="button"
            className="secondary"
            disabled={!canGoHistoryPrev || isLoading}
            onClick={() => {
              setHistoryOffset((current) => Math.max(0, current - historyLimit));
            }}
          >
            前へ
          </button>
          <span className="muted">
            {historyTotal === 0
              ? '0 / 0'
              : `${historyOffset + 1}-${Math.min(historyOffset + historyLimit, historyTotal)} / ${historyTotal}`}
          </span>
          <button
            type="button"
            className="secondary"
            disabled={!canGoHistoryNext || isLoading}
            onClick={() => {
              setHistoryOffset((current) => current + historyLimit);
            }}
          >
            次へ
          </button>
        </div>
      </section>
    </AppLayout>
  );
};

import { useState, type FormEvent } from 'react';
import type {
  MetricType,
  NotifyChannel,
  NotifyTiming,
  XAccountLink,
  WatchlistItem,
} from '../types/watchlist';

export interface WatchlistFormValues {
  ticker: string;
  name: string;
  metric_type: MetricType;
  notify_channel: NotifyChannel;
  notify_timing: NotifyTiming;
  reason: string;
  ir_urls_text: string;
  x_official_account: string;
  x_executive_accounts_text: string;
  is_active: boolean;
  ai_enabled: boolean;
}

interface WatchlistFormProps {
  mode: 'create' | 'edit';
  initialValue?: WatchlistItem;
  submitting: boolean;
  apiErrorMessage?: string;
  onSubmit: (values: WatchlistFormValues) => Promise<void>;
  onCancel: () => void;
}

const TICKER_PATTERN = /^\d{4}:TSE$/;

const buildInitialValues = (item?: WatchlistItem): WatchlistFormValues => {
  return {
    ticker: item?.ticker ?? '',
    name: item?.name ?? '',
    metric_type: item?.metric_type ?? 'PER',
    notify_channel: item?.notify_channel ?? 'DISCORD',
    notify_timing: item?.notify_timing ?? 'IMMEDIATE',
    reason: '',
    ir_urls_text: (item?.ir_urls ?? []).join('\n'),
    x_official_account: item?.x_official_account ?? '',
    x_executive_accounts_text: formatExecutiveAccounts(item?.x_executive_accounts ?? []),
    is_active: item?.is_active ?? true,
    ai_enabled: item?.ai_enabled ?? false,
  };
};

const formatExecutiveAccounts = (rows: XAccountLink[]): string => {
  return rows
    .map((row) => {
      const role = row.role?.trim() ?? '';
      return role.length > 0 ? `${row.handle},${role}` : row.handle;
    })
    .join('\n');
};

const parseMultilineValues = (value: string): string[] => {
  return value
    .split(/\r?\n/)
    .map((row) => row.trim())
    .filter((row) => row.length > 0);
};

const parseExecutiveAccounts = (value: string): XAccountLink[] => {
  return parseMultilineValues(value).map((row) => {
    const [handleRaw, ...roleParts] = row.split(',');
    return {
      handle: handleRaw.trim(),
      role: roleParts.join(',').trim() || undefined,
    };
  });
};

export const WatchlistForm = ({
  mode,
  initialValue,
  submitting,
  apiErrorMessage,
  onSubmit,
  onCancel,
}: WatchlistFormProps) => {
  const [values, setValues] = useState<WatchlistFormValues>(buildInitialValues(initialValue));
  const [localError, setLocalError] = useState<string>('');

  const title = mode === 'create' ? '銘柄を追加' : '銘柄を編集';
  const canEditTicker = mode === 'create';
  const submitLabel = submitting ? '送信中...' : mode === 'create' ? '追加する' : '更新する';

  const updateField = <K extends keyof WatchlistFormValues>(
    key: K,
    value: WatchlistFormValues[K],
  ): void => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setLocalError('');

    const normalizedTicker = values.ticker.trim().toUpperCase();
    const normalizedName = values.name.trim();

    if (!TICKER_PATTERN.test(normalizedTicker)) {
      setLocalError('ticker は 1234:TSE 形式で入力してください。');
      return;
    }

    if (normalizedName.length === 0) {
      setLocalError('会社名は必須です。');
      return;
    }

    await onSubmit({
      ...values,
      ticker: normalizedTicker,
      name: normalizedName,
      x_official_account: values.x_official_account.trim(),
      ir_urls_text: values.ir_urls_text.trim(),
      x_executive_accounts_text: values.x_executive_accounts_text.trim(),
    });
  };

  return (
    <section className="panel">
      <div className="panel-header">
        <h2>{title}</h2>
      </div>
      <form className="watchlist-form" onSubmit={handleSubmit}>
        <label>
          ticker
          <input
            type="text"
            value={values.ticker}
            onChange={(event) => {
              updateField('ticker', event.target.value);
            }}
            placeholder="例: 7203:TSE"
            disabled={!canEditTicker}
            required
          />
        </label>

        <label>
          会社名
          <input
            type="text"
            value={values.name}
            onChange={(event) => {
              updateField('name', event.target.value);
            }}
            required
          />
        </label>

        <label>
          監視方式
          <select
            value={values.metric_type}
            onChange={(event) => {
              updateField('metric_type', event.target.value as MetricType);
            }}
          >
            <option value="PER">PER</option>
            <option value="PSR">PSR</option>
          </select>
        </label>

        <label>
          通知先
          <select
            value={values.notify_channel}
            onChange={(event) => {
              updateField('notify_channel', event.target.value as NotifyChannel);
            }}
          >
            <option value="DISCORD">DISCORD</option>
            <option value="OFF">OFF</option>
          </select>
        </label>

        <label>
          通知時間
          <select
            value={values.notify_timing}
            onChange={(event) => {
              updateField('notify_timing', event.target.value as NotifyTiming);
            }}
          >
            <option value="IMMEDIATE">IMMEDIATE</option>
            <option value="AT_21">AT_21</option>
            <option value="OFF">OFF</option>
          </select>
        </label>

        <label>
          追加理由メモ（任意）
          <input
            type="text"
            value={values.reason}
            onChange={(event) => {
              updateField('reason', event.target.value);
            }}
            placeholder="例: 決算前の監視強化"
          />
        </label>

        <label>
          IR URL（改行区切り）
          <textarea
            value={values.ir_urls_text}
            onChange={(event) => {
              updateField('ir_urls_text', event.target.value);
            }}
            placeholder={'https://example.com/ir\nhttps://example.com/ir/news'}
          />
        </label>

        <label>
          X公式アカウント（任意）
          <input
            type="text"
            value={values.x_official_account}
            onChange={(event) => {
              updateField('x_official_account', event.target.value);
            }}
            placeholder="@company_ir"
          />
        </label>

        <label>
          X役員アカウント（1行1件: handle,role）
          <textarea
            value={values.x_executive_accounts_text}
            onChange={(event) => {
              updateField('x_executive_accounts_text', event.target.value);
            }}
            placeholder={'ceo_account,CEO\ncfo_account,CFO'}
          />
        </label>

        <div className="check-field">
          <label>
            <input
              type="checkbox"
              checked={values.is_active}
              onChange={(event) => {
                updateField('is_active', event.target.checked);
              }}
            />
            有効
          </label>
          <label>
            <input
              type="checkbox"
              checked={values.ai_enabled}
              onChange={(event) => {
                updateField('ai_enabled', event.target.checked);
              }}
            />
            AI通知（未実装）
          </label>
        </div>
        <p className="muted">AI通知は第2段階で実装予定です（現状は設定値の保存のみ）。</p>

        {(localError || apiErrorMessage) && (
          <p className="error-text">{localError || apiErrorMessage}</p>
        )}

        <div className="form-actions">
          <button type="button" className="ghost" onClick={onCancel} disabled={submitting}>
            キャンセル
          </button>
          <button type="submit" className="primary" disabled={submitting}>
            {submitLabel}
          </button>
        </div>
      </form>
    </section>
  );
};

export const buildWatchlistPayload = (values: WatchlistFormValues) => {
  return {
    name: values.name,
    metric_type: values.metric_type,
    notify_channel: values.notify_channel,
    notify_timing: values.notify_timing,
    is_active: values.is_active,
    ai_enabled: values.ai_enabled,
    reason: values.reason.trim() || undefined,
    ir_urls: parseMultilineValues(values.ir_urls_text),
    x_official_account: values.x_official_account.trim() || undefined,
    x_executive_accounts: parseExecutiveAccounts(values.x_executive_accounts_text),
  };
};

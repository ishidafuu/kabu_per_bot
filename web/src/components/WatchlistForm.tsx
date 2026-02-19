import { useState, type FormEvent } from 'react';
import type {
  IrUrlCandidate,
  MetricType,
  NotifyTiming,
  XAccountLink,
  WatchlistItem,
} from '../types/watchlist';

export interface WatchlistFormValues {
  ticker: string;
  name: string;
  metric_type: MetricType;
  notify_timing: NotifyTiming;
  always_notify_enabled: boolean;
  reason: string;
  ir_urls_text: string;
  x_official_account: string;
  x_executive_accounts_text: string;
  is_active: boolean;
}

interface WatchlistFormProps {
  mode: 'create' | 'edit';
  initialValue?: WatchlistItem;
  submitting: boolean;
  apiErrorMessage?: string;
  titleId?: string;
  onSuggestIrUrls?: (input: { ticker: string; company_name: string; max_candidates?: number }) => Promise<IrUrlCandidate[]>;
  onSubmit: (values: WatchlistFormValues) => Promise<void>;
  onCancel: () => void;
}

const TICKER_PATTERN = /^\d{4}:TSE$/;

const buildInitialValues = (item?: WatchlistItem): WatchlistFormValues => {
  return {
    ticker: item?.ticker ?? '',
    name: item?.name ?? '',
    metric_type: item?.metric_type ?? 'PER',
    notify_timing: item?.notify_timing ?? 'IMMEDIATE',
    always_notify_enabled: item?.always_notify_enabled ?? false,
    reason: '',
    ir_urls_text: (item?.ir_urls ?? []).join('\n'),
    x_official_account: item?.x_official_account ?? '',
    x_executive_accounts_text: formatExecutiveAccounts(item?.x_executive_accounts ?? []),
    is_active: item?.is_active ?? true,
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

const mergeIrUrlText = (currentText: string, urls: string[]): string => {
  const existing = currentText
    .split(/\r?\n/)
    .map((row) => row.trim())
    .filter((row) => row.length > 0);
  const merged = [...existing];
  const seen = new Set(existing);
  urls.forEach((url) => {
    const normalized = url.trim();
    if (normalized.length === 0) {
      return;
    }
    if (seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    merged.push(normalized);
  });
  return merged.join('\n');
};

const isAddableIrCandidate = (candidate: IrUrlCandidate): boolean => {
  return candidate.validation_status !== 'INVALID';
};

export const WatchlistForm = ({
  mode,
  initialValue,
  submitting,
  apiErrorMessage,
  titleId,
  onSubmit,
  onSuggestIrUrls,
  onCancel,
}: WatchlistFormProps) => {
  const [values, setValues] = useState<WatchlistFormValues>(buildInitialValues(initialValue));
  const [localError, setLocalError] = useState<string>('');
  const [suggestionError, setSuggestionError] = useState<string>('');
  const [isSuggestingIr, setIsSuggestingIr] = useState<boolean>(false);
  const [irCandidates, setIrCandidates] = useState<IrUrlCandidate[]>([]);

  const title = mode === 'create' ? '銘柄を追加' : '銘柄を編集';
  const canEditTicker = mode === 'create';
  const submitLabel = submitting ? '送信中...' : mode === 'create' ? '追加する' : '更新する';

  const updateField = <K extends keyof WatchlistFormValues>(
    key: K,
    value: WatchlistFormValues[K],
  ): void => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const appendIrUrls = (urls: string[]): void => {
    setValues((prev) => ({
      ...prev,
      ir_urls_text: mergeIrUrlText(prev.ir_urls_text, urls),
    }));
  };

  const handleSuggestIrUrls = async (): Promise<void> => {
    if (!onSuggestIrUrls) {
      return;
    }
    setSuggestionError('');
    const normalizedTicker = values.ticker.trim().toUpperCase();
    const normalizedName = values.name.trim();
    if (!TICKER_PATTERN.test(normalizedTicker)) {
      setSuggestionError('候補取得の前に ticker を 1234:TSE 形式で入力してください。');
      return;
    }
    if (normalizedName.length === 0) {
      setSuggestionError('候補取得の前に会社名を入力してください。');
      return;
    }

    setIsSuggestingIr(true);
    try {
      const rows = await onSuggestIrUrls({
        ticker: normalizedTicker,
        company_name: normalizedName,
        max_candidates: 5,
      });
      setIrCandidates(rows);
      if (rows.length === 0) {
        setSuggestionError('候補URLが見つかりませんでした。手入力で登録してください。');
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '候補取得に失敗しました。';
      setSuggestionError(message);
      setIrCandidates([]);
    } finally {
      setIsSuggestingIr(false);
    }
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

  const addableCandidates = irCandidates.filter(isAddableIrCandidate);

  return (
    <section className="panel">
      <div className="panel-header">
        <h2 id={titleId}>{title}</h2>
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
            autoFocus={canEditTicker}
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
            autoFocus={!canEditTicker}
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
        {onSuggestIrUrls && (
          <div className="ir-candidate-block">
            <div className="inline-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => void handleSuggestIrUrls()}
                disabled={isSuggestingIr || submitting}
              >
                {isSuggestingIr ? 'IR候補を取得中...' : 'IR候補を取得'}
              </button>
              {irCandidates.length > 0 && (
                <button
                  type="button"
                  className="ghost"
                  onClick={() => appendIrUrls(addableCandidates.map((row) => row.url))}
                  disabled={isSuggestingIr || submitting || addableCandidates.length === 0}
                >
                  追加可能候補を全件追加
                </button>
              )}
            </div>
            {suggestionError && <p className="error-text">{suggestionError}</p>}
            {irCandidates.length > 0 && (
              <div className="ir-candidate-list">
                {irCandidates.map((row) => (
                  <div key={row.url} className="ir-candidate-item">
                    <p>
                      <strong>{row.title || row.url}</strong>
                    </p>
                    <p className="muted">{row.url}</p>
                    <p className="muted">{`${row.validation_status} / score=${row.score} / confidence=${row.confidence}`}</p>
                    <p className="muted">{row.reason}</p>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => appendIrUrls([row.url])}
                      disabled={isSuggestingIr || submitting || !isAddableIrCandidate(row)}
                    >
                      {isAddableIrCandidate(row) ? 'このURLを追加' : 'このURLは追加不可'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

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
              checked={values.always_notify_enabled}
              onChange={(event) => {
                updateField('always_notify_enabled', event.target.checked);
              }}
            />
            常時通知（割安でない場合も通知）
          </label>
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
        </div>
        <p className="muted">AI要約通知は常時有効です（全銘柄対象）。</p>

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

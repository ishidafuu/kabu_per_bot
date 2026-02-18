import { useCallback, useEffect, useMemo, useState, type MouseEvent } from 'react';
import { useAuth } from '../auth/useAuth';
import { AppLayout } from '../components/AppLayout';
import { WatchlistForm, type WatchlistFormValues } from '../components/WatchlistForm';
import { createWatchlistClient } from '../lib/api';
import { toUserMessage } from '../lib/api/errors';
import { buildWatchlistPayload } from '../lib/watchlistFormPayload';
import { appConfig } from '../lib/config';
import type { WatchlistItem } from '../types/watchlist';

const getPageLabel = (offset: number, limit: number): number => {
  return Math.floor(offset / limit) + 1;
};

const formatMetric = (value: number | null | undefined): string => {
  if (value == null) {
    return '-';
  }
  return value.toFixed(2);
};

const formatEarnings = (date?: string | null, time?: string | null): string => {
  if (!date) {
    return '-';
  }
  return `${date} ${time ?? '未定'}`;
};

export const WatchlistPage = () => {
  const { getIdToken } = useAuth();
  const client = useMemo(() => createWatchlistClient({ getToken: getIdToken }), [getIdToken]);

  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [total, setTotal] = useState(0);
  const [keywordInput, setKeywordInput] = useState('');
  const [keyword, setKeyword] = useState('');
  const [offset, setOffset] = useState(0);
  const limit = appConfig.pageSize;
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [noticeMessage, setNoticeMessage] = useState('');
  const [editingItem, setEditingItem] = useState<WatchlistItem | null>(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [isSubmittingForm, setIsSubmittingForm] = useState(false);
  const [formError, setFormError] = useState('');

  const closeForm = useCallback((options?: { force?: boolean }): void => {
    if (isSubmittingForm && !options?.force) {
      return;
    }
    setIsFormOpen(false);
    setEditingItem(null);
    setFormError('');
  }, [isSubmittingForm]);

  useEffect(() => {
    if (!isFormOpen) {
      return;
    }

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleEscKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        closeForm();
      }
    };

    window.addEventListener('keydown', handleEscKey);
    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener('keydown', handleEscKey);
    };
  }, [isFormOpen, closeForm]);

  const fetchWatchlist = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setLoadError('');

    try {
      const response = await client.list({
        q: keyword || undefined,
        limit,
        offset,
        include_status: true,
      });
      setItems(response.items);
      setTotal(response.total);
    } catch (error) {
      setLoadError(toUserMessage(error));
      setItems([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  }, [client, keyword, limit, offset]);

  useEffect(() => {
    void fetchWatchlist();
  }, [fetchWatchlist]);

  const handleSearch = (): void => {
    setOffset(0);
    setKeyword(keywordInput.trim());
  };

  const handleDelete = async (ticker: string): Promise<void> => {
    const accepted = window.confirm(`${ticker} を削除します。よろしいですか？`);

    if (!accepted) {
      return;
    }
    const reason = window.prompt('削除理由メモ（任意）', '') ?? '';

    setNoticeMessage('');

    try {
      await client.remove(ticker, reason);
      setNoticeMessage(`削除しました: ${ticker}`);
      await fetchWatchlist();
    } catch (error) {
      setNoticeMessage(toUserMessage(error));
    }
  };

  const openCreateForm = (): void => {
    closeForm();
    setIsFormOpen(true);
  };

  const openEditForm = (item: WatchlistItem): void => {
    setEditingItem(item);
    setFormError('');
    setIsFormOpen(true);
  };

  const handleFormSubmit = async (values: WatchlistFormValues): Promise<void> => {
    setNoticeMessage('');
    setFormError('');
    setIsSubmittingForm(true);

    try {
      const payload = buildWatchlistPayload(values);

      if (!editingItem) {
        await client.create({
          ticker: values.ticker,
          ...payload,
        });
        setNoticeMessage(`追加しました: ${values.ticker}`);
      } else {
        await client.update(editingItem.ticker, payload);
        setNoticeMessage(`更新しました: ${editingItem.ticker}`);
      }

      closeForm({ force: true });
      await fetchWatchlist();
    } catch (error) {
      setFormError(toUserMessage(error));
    } finally {
      setIsSubmittingForm(false);
    }
  };

  const maxOffset = Math.max(total - limit, 0);
  const canGoPrev = offset > 0;
  const canGoNext = offset + limit < total;

  const handleModalBackdropClick = (event: MouseEvent<HTMLDivElement>): void => {
    if (event.target === event.currentTarget) {
      closeForm();
    }
  };

  return (
    <AppLayout title="ウォッチリスト管理">
      <section className="panel controls-panel">
        <div className="search-row">
          <input
            type="search"
            placeholder="ticker / 会社名で検索"
            value={keywordInput}
            onChange={(event) => {
              setKeywordInput(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                handleSearch();
              }
            }}
          />
          <button type="button" className="secondary" onClick={handleSearch}>
            検索
          </button>
          <button type="button" className="primary" onClick={openCreateForm}>
            新規追加
          </button>
        </div>

        <div className="meta-row">
          <span>総件数: {total}</span>
          <span>ページ: {getPageLabel(offset, limit)}</span>
          <span>表示件数: {limit}</span>
        </div>
      </section>

      {noticeMessage && <p className="notice-text">{noticeMessage}</p>}
      {loadError && <p className="error-text">{loadError}</p>}

      <section className="panel table-panel">
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>銘柄コード</th>
                <th>会社名</th>
                <th>監視指標</th>
                <th>通知タイミング</th>
                <th>常時通知</th>
                <th>有効状態</th>
                <th>現在値</th>
                <th>中央値（1W/3M/1Y）</th>
                <th>シグナル</th>
                <th>次回決算</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {!isLoading && items.length === 0 && (
                <tr>
                  <td colSpan={11} className="empty-cell">
                    データがありません。
                  </td>
                </tr>
              )}

              {items.map((item) => (
                <tr key={item.ticker}>
                  <td>{item.ticker}</td>
                  <td>{item.name}</td>
                  <td>{item.metric_type}</td>
                  <td>{item.notify_timing}</td>
                  <td>{item.always_notify_enabled ? 'true' : 'false'}</td>
                  <td>{item.is_active ? 'true' : 'false'}</td>
                  <td>{formatMetric(item.current_metric_value)}</td>
                  <td>
                    {`${formatMetric(item.median_1w)} / ${formatMetric(item.median_3m)} / ${formatMetric(item.median_1y)}`}
                  </td>
                  <td>
                    {item.signal_category ? `${item.signal_category} ${item.signal_combo ?? ''}` : '-'}
                    {item.signal_streak_days ? ` (${item.signal_streak_days}日連続)` : ''}
                  </td>
                  <td>{formatEarnings(item.next_earnings_date, item.next_earnings_time)}</td>
                  <td>
                    <div className="inline-actions">
                      <button type="button" className="ghost" onClick={() => openEditForm(item)}>
                        編集
                      </button>
                      <button
                        type="button"
                        className="danger"
                        onClick={() => void handleDelete(item.ticker)}
                      >
                        削除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="pagination-row">
          <button
            type="button"
            className="ghost"
            disabled={!canGoPrev || isLoading}
            onClick={() => {
              setOffset((prev) => Math.max(prev - limit, 0));
            }}
          >
            前へ
          </button>
          <button
            type="button"
            className="ghost"
            disabled={!canGoNext || isLoading}
            onClick={() => {
              setOffset((prev) => Math.min(prev + limit, maxOffset));
            }}
          >
            次へ
          </button>
        </div>
      </section>

      {isFormOpen && (
        <div className="modal-overlay" onClick={handleModalBackdropClick}>
          <div
            className="modal-dialog watchlist-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="watchlist-form-title"
          >
            <button
              type="button"
              className="modal-close ghost"
              onClick={() => closeForm()}
              aria-label="編集フォームを閉じる"
              disabled={isSubmittingForm}
            >
              ×
            </button>
            <WatchlistForm
              key={editingItem?.ticker ?? 'create'}
              mode={editingItem ? 'edit' : 'create'}
              initialValue={editingItem ?? undefined}
              submitting={isSubmittingForm}
              apiErrorMessage={formError}
              onSubmit={handleFormSubmit}
              onCancel={closeForm}
              titleId="watchlist-form-title"
            />
          </div>
        </div>
      )}
    </AppLayout>
  );
};

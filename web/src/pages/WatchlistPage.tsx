import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { WatchlistForm, type WatchlistFormValues } from '../components/WatchlistForm';
import { createWatchlistClient } from '../lib/api';
import { toUserMessage } from '../lib/api/errors';
import { appConfig } from '../lib/config';
import type { WatchlistItem } from '../types/watchlist';

const getPageLabel = (offset: number, limit: number): number => {
  return Math.floor(offset / limit) + 1;
};

export const WatchlistPage = () => {
  const { user, logout, getIdToken } = useAuth();
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

  const closeForm = (): void => {
    setIsFormOpen(false);
    setEditingItem(null);
    setFormError('');
  };

  const fetchWatchlist = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setLoadError('');

    try {
      const response = await client.list({
        q: keyword || undefined,
        limit,
        offset,
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

    setNoticeMessage('');

    try {
      await client.remove(ticker);
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
      const payload = {
        name: values.name,
        metric_type: values.metric_type,
        notify_channel: values.notify_channel,
        notify_timing: values.notify_timing,
        is_active: values.is_active,
        ai_enabled: values.ai_enabled,
      };

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

      closeForm();
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

  return (
    <main className="page-shell">
      <header className="top-bar panel">
        <div>
          <h1>ウォッチリスト管理</h1>
          <p className="muted">ログイン中: {user?.email ?? 'unknown'}</p>
        </div>
        <div className="top-actions">
          <Link to="/dashboard" className="nav-link">
            ダッシュボードへ
          </Link>
          <button type="button" className="ghost" onClick={() => void logout()}>
            ログアウト
          </button>
        </div>
      </header>

      <nav className="panel page-nav" aria-label="ページ遷移">
        <NavLink
          to="/watchlist"
          end
          className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
        >
          ウォッチリスト
        </NavLink>
        <NavLink
          to="/watchlist/history"
          className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
        >
          履歴
        </NavLink>
        <NavLink
          to="/notifications/logs"
          className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
        >
          通知ログ
        </NavLink>
      </nav>

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
                <th>ticker</th>
                <th>name</th>
                <th>metric_type</th>
                <th>notify_channel</th>
                <th>notify_timing</th>
                <th>is_active</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {!isLoading && items.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty-cell">
                    データがありません。
                  </td>
                </tr>
              )}

              {items.map((item) => (
                <tr key={item.ticker}>
                  <td>{item.ticker}</td>
                  <td>{item.name}</td>
                  <td>{item.metric_type}</td>
                  <td>{item.notify_channel}</td>
                  <td>{item.notify_timing}</td>
                  <td>{item.is_active ? 'true' : 'false'}</td>
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
        <WatchlistForm
          key={editingItem?.ticker ?? 'create'}
          mode={editingItem ? 'edit' : 'create'}
          initialValue={editingItem ?? undefined}
          submitting={isSubmittingForm}
          apiErrorMessage={formError}
          onSubmit={handleFormSubmit}
          onCancel={closeForm}
        />
      )}
    </main>
  );
};

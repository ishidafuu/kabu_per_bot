import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { AppLayout } from '../components/AppLayout';
import { createNotificationLogClient } from '../lib/api';
import { toUserMessage } from '../lib/api/errors';
import { appConfig } from '../lib/config';
import type { NotificationLogItem } from '../types/notificationLog';

const getPageLabel = (offset: number, limit: number): number => {
  return Math.floor(offset / limit) + 1;
};

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

const formatDateTime = (value: string): string => {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return dateTimeFormatter.format(date);
};

export const NotificationLogsPage = () => {
  const { getIdToken } = useAuth();
  const client = useMemo(() => createNotificationLogClient({ getToken: getIdToken }), [getIdToken]);

  const [items, setItems] = useState<NotificationLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [tickerInput, setTickerInput] = useState('');
  const [ticker, setTicker] = useState('');
  const [offset, setOffset] = useState(0);
  const limit = appConfig.pageSize;
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState('');

  const fetchLogs = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setLoadError('');

    try {
      const response = await client.list({
        ticker: ticker || undefined,
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
  }, [client, ticker, limit, offset]);

  useEffect(() => {
    void fetchLogs();
  }, [fetchLogs]);

  const handleSearch = (): void => {
    setOffset(0);
    setTicker(tickerInput.trim().toUpperCase());
  };

  const maxOffset = Math.max(total - limit, 0);
  const canGoPrev = offset > 0;
  const canGoNext = offset + limit < total;

  return (
    <AppLayout title="通知ログ">
      <section className="panel controls-panel">
        <div className="search-row compact">
          <input
            type="search"
            placeholder="tickerで絞り込み (例: 7203:TSE)"
            value={tickerInput}
            onChange={(event) => {
              setTickerInput(event.target.value);
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
        </div>

        <div className="meta-row">
          <span>総件数: {total}</span>
          <span>ページ: {getPageLabel(offset, limit)}</span>
          <span>表示件数: {limit}</span>
          <span>絞り込み: {ticker || 'なし'}</span>
        </div>
      </section>

      {loadError && <p className="error-text">{loadError}</p>}

      <section className="panel table-panel">
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>送信日時</th>
                <th>銘柄コード</th>
                <th>通知カテゴリ</th>
                <th>通知先</th>
                <th>強通知</th>
                <th>条件キー</th>
                <th>通知ID</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && items.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty-cell">
                    読み込み中...
                  </td>
                </tr>
              )}

              {!isLoading && items.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty-cell">
                    通知ログがありません。
                  </td>
                </tr>
              )}

              {items.map((item) => (
                <tr key={item.entry_id}>
                  <td>{formatDateTime(item.sent_at)}</td>
                  <td>{item.ticker}</td>
                  <td>{item.category}</td>
                  <td>{item.channel}</td>
                  <td>{item.is_strong ? 'true' : 'false'}</td>
                  <td>{item.condition_key}</td>
                  <td>{item.entry_id}</td>
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
    </AppLayout>
  );
};

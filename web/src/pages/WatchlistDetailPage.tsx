import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { AppLayout } from '../components/AppLayout';
import { createWatchlistClient } from '../lib/api';
import { toUserMessage } from '../lib/api/errors';
import { appConfig } from '../lib/config';
import type { WatchlistDetailResponse } from '../types/watchlistDetail';

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
  const limit = appConfig.pageSize;
  const historyLimit = 10;
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState('');

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

  const notificationTotal = detail?.notifications.total ?? 0;
  const historyTotal = detail?.history.total ?? 0;
  const canGoNotificationPrev = offset > 0;
  const canGoNotificationNext = offset + limit < notificationTotal;
  const canGoHistoryPrev = historyOffset > 0;
  const canGoHistoryNext = historyOffset + historyLimit < historyTotal;

  const item = detail?.item;
  const summary = detail?.summary;

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
                  <td>{row.is_strong ? 'true' : 'false'}</td>
                  <td>{row.condition_key}</td>
                  <td className="detail-body-cell">{row.body ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination-row">
          <span className="muted">総件数: {notificationTotal}</span>
          <button
            type="button"
            className="ghost"
            disabled={!canGoNotificationPrev || isLoading}
            onClick={() => {
              setOffset((prev) => Math.max(prev - limit, 0));
            }}
          >
            前へ
          </button>
          <button
            type="button"
            className="ghost"
            disabled={!canGoNotificationNext || isLoading}
            onClick={() => {
              setOffset((prev) => prev + limit);
            }}
          >
            次へ
          </button>
        </div>
      </section>

      <section className="panel table-panel detail-table-panel">
        <div className="panel-header">
          <h2>ウォッチリスト操作履歴</h2>
        </div>
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>操作日時</th>
                <th>操作種別</th>
                <th>理由メモ</th>
                <th>履歴ID</th>
              </tr>
            </thead>
            <tbody>
              {!isLoading && (detail?.history.items.length ?? 0) === 0 && (
                <tr>
                  <td colSpan={4} className="empty-cell">
                    履歴データがありません。
                  </td>
                </tr>
              )}
              {detail?.history.items.map((row) => (
                <tr key={row.record_id}>
                  <td>{formatDateTime(row.acted_at)}</td>
                  <td>{row.action}</td>
                  <td>{row.reason ?? '-'}</td>
                  <td>{row.record_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pagination-row">
          <span className="muted">総件数: {historyTotal}</span>
          <button
            type="button"
            className="ghost"
            disabled={!canGoHistoryPrev || isLoading}
            onClick={() => {
              setHistoryOffset((prev) => Math.max(prev - historyLimit, 0));
            }}
          >
            前へ
          </button>
          <button
            type="button"
            className="ghost"
            disabled={!canGoHistoryNext || isLoading}
            onClick={() => {
              setHistoryOffset((prev) => prev + historyLimit);
            }}
          >
            次へ
          </button>
        </div>
      </section>
    </AppLayout>
  );
};

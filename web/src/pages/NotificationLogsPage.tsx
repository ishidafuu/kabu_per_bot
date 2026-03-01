import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { AppLayout } from '../components/AppLayout';
import { createNotificationLogClient } from '../lib/api';
import { toUserMessage } from '../lib/api/errors';
import { appConfig } from '../lib/config';
import type { CommitteeLogSummary, NotificationLogItem } from '../types/notificationLog';
import type { WatchPriority } from '../types/watchlist';

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

export const NotificationLogsPage = () => {
  const { getIdToken } = useAuth();
  const client = useMemo(() => createNotificationLogClient({ getToken: getIdToken }), [getIdToken]);

  const [items, setItems] = useState<NotificationLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [tickerInput, setTickerInput] = useState('');
  const [ticker, setTicker] = useState('');
  const [priority, setPriority] = useState<WatchPriority | ''>('');
  const [category, setCategory] = useState<string>('');
  const [evaluationConfidenceMin, setEvaluationConfidenceMin] = useState<number | ''>('');
  const [evaluationStrengthMin, setEvaluationStrengthMin] = useState<number | ''>('');
  const [offset, setOffset] = useState(0);
  const limit = appConfig.pageSize;
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [committeeSummary, setCommitteeSummary] = useState<CommitteeLogSummary | null>(null);

  const fetchLogs = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setLoadError('');

    try {
      const [listResult, summaryResult] = await Promise.allSettled([
        client.list({
          ticker: ticker || undefined,
          priority: priority || undefined,
          category: category || undefined,
          evaluationConfidenceMin: evaluationConfidenceMin === '' ? undefined : evaluationConfidenceMin,
          evaluationStrengthMin: evaluationStrengthMin === '' ? undefined : evaluationStrengthMin,
          limit,
          offset,
        }),
        client.getCommitteeSummary(7),
      ]);

      if (listResult.status === 'rejected') {
        throw listResult.reason;
      }

      setItems(listResult.value.items);
      setTotal(listResult.value.total);

      if (summaryResult.status === 'fulfilled') {
        setCommitteeSummary(summaryResult.value);
      } else {
        setCommitteeSummary(null);
        setLoadError('委員会評価サマリの取得に失敗しました。ログ一覧のみ表示しています。');
      }
    } catch (error) {
      setLoadError(toUserMessage(error));
      setItems([]);
      setTotal(0);
      setCommitteeSummary(null);
    } finally {
      setIsLoading(false);
    }
  }, [client, ticker, priority, category, evaluationConfidenceMin, evaluationStrengthMin, limit, offset]);

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
        <p className="muted">🔔 通知の発生条件を追跡したいときは、まず ticker で絞り込んで確認してください。</p>
        <div className="search-row compact notification-logs-search-row">
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
          <select
            value={priority}
            onChange={(event) => {
              setOffset(0);
              setPriority(event.target.value as WatchPriority | '');
            }}
            aria-label="優先度で絞り込み"
          >
            <option value="">優先度: すべて</option>
            <option value="HIGH">HIGH</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="LOW">LOW</option>
          </select>
          <select
            value={category}
            onChange={(event) => {
              setOffset(0);
              setCategory(event.target.value);
            }}
            aria-label="カテゴリで絞り込み"
          >
            <option value="">カテゴリ: すべて</option>
            <option value="委員会評価">委員会評価</option>
          </select>
          <select
            value={evaluationConfidenceMin}
            onChange={(event) => {
              setOffset(0);
              const raw = event.target.value;
              setEvaluationConfidenceMin(raw ? Number(raw) : '');
            }}
            aria-label="自信下限で絞り込み"
          >
            <option value="">自信下限: なし</option>
            <option value="1">1以上</option>
            <option value="2">2以上</option>
            <option value="3">3以上</option>
            <option value="4">4以上</option>
            <option value="5">5以上</option>
          </select>
          <select
            value={evaluationStrengthMin}
            onChange={(event) => {
              setOffset(0);
              const raw = event.target.value;
              setEvaluationStrengthMin(raw ? Number(raw) : '');
            }}
            aria-label="強さ下限で絞り込み"
          >
            <option value="">強さ下限: なし</option>
            <option value="1">1以上</option>
            <option value="2">2以上</option>
            <option value="3">3以上</option>
            <option value="4">4以上</option>
            <option value="5">5以上</option>
          </select>
        </div>

        <div className="meta-row">
          <span>総件数: {total}</span>
          <span>ページ: {getPageLabel(offset, limit)}</span>
          <span>表示件数: {limit}</span>
          <span>絞り込み: {ticker || 'なし'}</span>
          <span>優先度: {priority || 'すべて'}</span>
          <span>カテゴリ: {category || 'すべて'}</span>
        </div>
        {committeeSummary && (
          <div className="meta-row">
            <span>委員会評価(7日): {committeeSummary.total}件</span>
            <span>
              強さ分布:
              {` 1:${committeeSummary.strength_distribution['1']} 2:${committeeSummary.strength_distribution['2']} 3:${committeeSummary.strength_distribution['3']} 4:${committeeSummary.strength_distribution['4']} 5:${committeeSummary.strength_distribution['5']}`}
            </span>
            <span>
              自信分布:
              {` 1:${committeeSummary.confidence_distribution['1']} 2:${committeeSummary.confidence_distribution['2']} 3:${committeeSummary.confidence_distribution['3']} 4:${committeeSummary.confidence_distribution['4']} 5:${committeeSummary.confidence_distribution['5']}`}
            </span>
          </div>
        )}
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
                <th>データソース</th>
                <th>取得時刻</th>
                <th>自信</th>
                <th>強さ</th>
                <th>本文</th>
                <th>通知ID</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && items.length === 0 && (
                <tr>
                  <td colSpan={12} className="empty-cell">
                    読み込み中...
                  </td>
                </tr>
              )}

              {!isLoading && items.length === 0 && (
                <tr>
                  <td colSpan={12} className="empty-cell">
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
                  <td>{item.data_source ?? '-'}</td>
                  <td>{formatDateTime(item.data_fetched_at)}</td>
                  <td>{item.evaluation_confidence ?? '-'}</td>
                  <td>{item.evaluation_strength ?? '-'}</td>
                  <td className="detail-body-cell">{item.body ?? '-'}</td>
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

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { createDashboardClient } from '../lib/api';
import { toUserMessage } from '../lib/api/errors';
import type { DashboardSummary } from '../types/dashboard';

const formatFailedJob = (value: boolean | null): string => {
  if (value == null) {
    return '取得不可';
  }

  return value ? 'あり' : 'なし';
};

const getFailedJobClassName = (value: boolean | null): string => {
  if (value == null) {
    return 'status-unknown';
  }

  return value ? 'status-error' : 'status-ok';
};

export const DashboardPage = () => {
  const { user, logout, getIdToken } = useAuth();
  const client = useMemo(() => createDashboardClient({ getToken: getIdToken }), [getIdToken]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  const fetchSummary = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setLoadError('');

    try {
      const response = await client.getSummary();
      setSummary(response);
    } catch (error) {
      setSummary(null);
      setLoadError(toUserMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void fetchSummary();
  }, [fetchSummary]);

  return (
    <main className="page-shell">
      <header className="top-bar panel">
        <div>
          <h1>ダッシュボード</h1>
          <p className="muted">ログイン中: {user?.email ?? 'unknown'}</p>
        </div>
        <div className="top-actions">
          <Link to="/watchlist" className="nav-link">
            ウォッチリストへ
          </Link>
          <button type="button" className="ghost" onClick={() => void logout()}>
            ログアウト
          </button>
        </div>
      </header>

      <section className="panel controls-panel">
        <div className="meta-row">
          <span>運用主要KPI</span>
        </div>
        <button
          type="button"
          className="secondary fit-content"
          disabled={isLoading}
          onClick={() => void fetchSummary()}
        >
          {isLoading ? '読込中...' : '再読み込み'}
        </button>
      </section>

      {isLoading && !summary && (
        <section className="panel state-panel">
          <p className="muted">ダッシュボード集計を読み込み中です...</p>
        </section>
      )}

      {loadError && (
        <section className="panel state-panel">
          <p className="error-text">{loadError}</p>
        </section>
      )}

      {summary && (
        <section className="kpi-grid">
          <article className="panel kpi-card">
            <p className="kpi-label">監視銘柄数</p>
            <p className="kpi-value">{summary.watchlist_count}</p>
          </article>
          <article className="panel kpi-card">
            <p className="kpi-label">当日通知件数</p>
            <p className="kpi-value">{summary.today_notification_count}</p>
          </article>
          <article className="panel kpi-card">
            <p className="kpi-label">データ不明件数</p>
            <p className="kpi-value">{summary.today_data_unknown_count}</p>
          </article>
          <article className="panel kpi-card">
            <p className="kpi-label">失敗ジョブ有無</p>
            <p className={`kpi-value ${getFailedJobClassName(summary.failed_job_exists)}`}>
              {formatFailedJob(summary.failed_job_exists)}
            </p>
          </article>
        </section>
      )}
    </main>
  );
};

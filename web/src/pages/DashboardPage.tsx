import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { AppLayout } from '../components/AppLayout';
import { createDashboardClient } from '../lib/api';
import { toUserMessage } from '../lib/api/errors';
import type { DashboardSummary } from '../types/dashboard';

const formatFailedJob = (value: boolean): string => {
  return value ? 'あり' : 'なし';
};

const getFailedJobClassName = (value: boolean): string => {
  return value ? 'status-error' : 'status-ok';
};

export const DashboardPage = () => {
  const { getIdToken } = useAuth();
  const client = useMemo(() => createDashboardClient({ getToken: getIdToken }), [getIdToken]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  const fetchSummary = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setLoadError('');
    try {
      const summaryResponse = await client.getSummary();
      setSummary(summaryResponse);
    } catch (error) {
      setLoadError(toUserMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void fetchSummary();
  }, [fetchSummary]);

  return (
    <AppLayout title="ダッシュボード">
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
        <p className="muted">ジョブ実行やDiscord疎通テストは「運用操作」ページに集約しています。</p>
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
    </AppLayout>
  );
};

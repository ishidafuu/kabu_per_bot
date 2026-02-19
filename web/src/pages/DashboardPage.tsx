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
    <AppLayout title="ダッシュボード" subtitle="毎日の最初に見る数値を、トレーダー向けに整理しています。">
      <section className="panel dashboard-hero">
        <div className="dashboard-hero-row">
          <p className="dashboard-badge">本日の運用サマリ</p>
          <button
            type="button"
            className="secondary fit-content"
            disabled={isLoading}
            onClick={() => void fetchSummary()}
          >
            {isLoading ? '読込中...' : '再読み込み'}
          </button>
        </div>
        <h2>今日の確認ポイント</h2>
        <p className="muted">1. 失敗ジョブ有無 2. データ不明件数 3. 当日通知件数 の順で確認すると、異常を早く検知できます。</p>
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
        <section className="kpi-grid dashboard-kpi-grid">
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

      <section className="panel dashboard-checklist">
        <h3>運用メモ</h3>
        <ul className="guide-list">
          <li>「失敗ジョブ有無」が `あり` の日は、先に通知ログで当日配信を確認します。</li>
          <li>「データ不明件数」が増えた日は、ウォッチリストの `現在値` 列もあわせて確認します。</li>
          <li>銘柄設定を変更した日は、履歴ページで操作記録を確認します。</li>
        </ul>
      </section>
    </AppLayout>
  );
};

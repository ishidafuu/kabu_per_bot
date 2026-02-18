import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';
import { createDashboardClient } from '../lib/api';
import { ApiError, toUserMessage } from '../lib/api/errors';
import type {
  AdminJobKey,
  AdminOpsExecution,
  AdminOpsSummary,
  BackfillRunPayload,
  DashboardSummary,
} from '../types/dashboard';

const formatFailedJob = (value: boolean): string => {
  return value ? 'あり' : 'なし';
};

const getFailedJobClassName = (value: boolean): string => {
  return value ? 'status-error' : 'status-ok';
};

const formatExecutionStatus = (value: string): string => {
  if (value === 'SUCCEEDED') {
    return '成功';
  }
  if (value === 'FAILED') {
    return '失敗';
  }
  if (value === 'RUNNING') {
    return '実行中';
  }
  if (value === 'PENDING') {
    return '待機中';
  }
  return value;
};

const getExecutionStatusClassName = (value: string): string => {
  if (value === 'SUCCEEDED') {
    return 'status-ok';
  }
  if (value === 'FAILED') {
    return 'status-error';
  }
  return 'status-unknown';
};

const formatTime = (value?: string | null): string => {
  if (!value) {
    return '-';
  }
  return new Date(value).toLocaleString('ja-JP', { hour12: false });
};

export const DashboardPage = () => {
  const { user, logout, getIdToken } = useAuth();
  const client = useMemo(() => createDashboardClient({ getToken: getIdToken }), [getIdToken]);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [opsSummary, setOpsSummary] = useState<AdminOpsSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [opsError, setOpsError] = useState('');
  const [opsForbidden, setOpsForbidden] = useState(false);
  const [opNotice, setOpNotice] = useState('');
  const [runningJobKey, setRunningJobKey] = useState<AdminJobKey | 'discord_test' | null>(null);
  const [backfillForm, setBackfillForm] = useState<BackfillRunPayload>({
    from_date: '',
    to_date: '',
    tickers: [],
    dry_run: true,
  });
  const [backfillTickersText, setBackfillTickersText] = useState('');

  const fetchSummary = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setLoadError('');
    setOpsError('');
    setOpsForbidden(false);

    try {
      const summaryResponse = await client.getSummary();
      setSummary(summaryResponse);
    } catch (error) {
      setLoadError(toUserMessage(error));
    }

    try {
      const opsResponse = await client.getAdminOpsSummary();
      setOpsSummary(opsResponse);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        setOpsForbidden(true);
        setOpsSummary(null);
      } else {
        setOpsError(toUserMessage(error));
      }
    } finally {
      setIsLoading(false);
    }
  }, [client]);

  const refreshOps = useCallback(async (): Promise<void> => {
    if (opsForbidden) {
      return;
    }
    setOpsError('');
    try {
      const response = await client.getAdminOpsSummary();
      setOpsSummary(response);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        setOpsForbidden(true);
        setOpsSummary(null);
        return;
      }
      setOpsError(toUserMessage(error));
    }
  }, [client, opsForbidden]);

  const runJob = useCallback(
    async (jobKey: AdminJobKey, payload?: BackfillRunPayload): Promise<void> => {
      setRunningJobKey(jobKey);
      setOpsError('');
      setOpNotice('');
      try {
        const response = await client.runAdminJob(jobKey, payload);
        setOpNotice(`実行を受け付けました: ${response.execution.execution_name}`);
        await refreshOps();
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          setOpsError(error.detail);
        } else {
          setOpsError(toUserMessage(error));
        }
      } finally {
        setRunningJobKey(null);
      }
    },
    [client, refreshOps],
  );

  const sendDiscordTest = useCallback(async (): Promise<void> => {
    setRunningJobKey('discord_test');
    setOpsError('');
    setOpNotice('');
    try {
      const response = await client.sendDiscordTest();
      setOpNotice(`Discord疎通テストを送信しました: ${formatTime(response.sent_at)}`);
    } catch (error) {
      setOpsError(toUserMessage(error));
    } finally {
      setRunningJobKey(null);
    }
  }, [client]);

  const handleBackfillRun = useCallback(async (): Promise<void> => {
    const normalizedTickers = backfillTickersText
      .split(',')
      .map((row) => row.trim())
      .filter((row) => row.length > 0);
    await runJob('backfill', {
      from_date: backfillForm.from_date,
      to_date: backfillForm.to_date,
      tickers: normalizedTickers,
      dry_run: backfillForm.dry_run,
    });
  }, [backfillForm, backfillTickersText, runJob]);

  useEffect(() => {
    void fetchSummary();
  }, [fetchSummary]);

  const jobRows = opsSummary?.jobs ?? [];
  const recentExecutions: AdminOpsExecution[] = opsSummary?.recent_executions ?? [];
  const latestSkipRows: AdminOpsExecution[] = opsSummary?.latest_skip_reasons ?? [];

  const isBackfillConfigured = jobRows.some((row) => row.key === 'backfill' && row.configured);

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
          <Link to="/guide" className="nav-link">
            使い方
          </Link>
          <button type="button" className="ghost" onClick={() => void logout()}>
            ログアウト
          </button>
        </div>
      </header>

      <nav className="panel page-nav">
        <Link to="/dashboard" className="nav-link active">
          ダッシュボード
        </Link>
        <Link to="/watchlist" className="nav-link">
          ウォッチリスト
        </Link>
        <Link to="/watchlist/history" className="nav-link">
          監視履歴
        </Link>
        <Link to="/notifications/logs" className="nav-link">
          通知ログ
        </Link>
        <Link to="/guide" className="nav-link">
          使い方
        </Link>
      </nav>

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

      <section className="panel controls-panel">
        <div className="meta-row">
          <span>運用操作（管理者）</span>
        </div>
        <div className="inline-actions">
          <button type="button" className="secondary" onClick={() => void refreshOps()} disabled={isLoading}>
            運用情報を更新
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void sendDiscordTest()}
            disabled={runningJobKey !== null || opsForbidden}
          >
            {runningJobKey === 'discord_test' ? '送信中...' : 'Discord疎通テスト'}
          </button>
        </div>
        {opsForbidden && <p className="muted">管理者権限がないため、運用操作は表示できません。</p>}
        {opsError && <p className="error-text">{opsError}</p>}
        {opNotice && <p className="notice-text">{opNotice}</p>}
      </section>

      {!opsForbidden && (
        <>
          <section className="panel controls-panel">
            <div className="meta-row">
              <span>ジョブ実行</span>
            </div>
            <div className="job-grid">
              {jobRows
                .filter((row) => row.key !== 'backfill')
                .map((row) => (
                  <article key={row.key} className="panel job-card">
                    <p className="kpi-label">{row.label}</p>
                    <p className="muted">job: {row.job_name ?? '未設定'}</p>
                    <button
                      type="button"
                      className="primary"
                      disabled={!row.configured || runningJobKey !== null}
                      onClick={() => void runJob(row.key)}
                    >
                      {runningJobKey === row.key ? '実行中...' : '実行'}
                    </button>
                  </article>
                ))}
            </div>
          </section>

          <section className="panel controls-panel">
            <div className="meta-row">
              <span>バックフィル実行</span>
            </div>
            <div className="backfill-form-grid">
              <label>
                from-date
                <input
                  type="date"
                  value={backfillForm.from_date}
                  onChange={(event) => setBackfillForm({ ...backfillForm, from_date: event.target.value })}
                />
              </label>
              <label>
                to-date
                <input
                  type="date"
                  value={backfillForm.to_date}
                  onChange={(event) => setBackfillForm({ ...backfillForm, to_date: event.target.value })}
                />
              </label>
              <label>
                tickers（任意 / カンマ区切り）
                <input
                  type="text"
                  placeholder="3984:TSE,6238:TSE"
                  value={backfillTickersText}
                  onChange={(event) => setBackfillTickersText(event.target.value)}
                />
              </label>
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={backfillForm.dry_run}
                  onChange={(event) => setBackfillForm({ ...backfillForm, dry_run: event.target.checked })}
                />
                dry-run
              </label>
              <button
                type="button"
                className="primary fit-content"
                disabled={!isBackfillConfigured || runningJobKey !== null}
                onClick={() => void handleBackfillRun()}
              >
                {runningJobKey === 'backfill' ? '実行中...' : 'バックフィル実行'}
              </button>
            </div>
            {!isBackfillConfigured && (
              <p className="muted">`OPS_BACKFILL_JOB_NAME` 未設定のため、バックフィル実行は無効です。</p>
            )}
          </section>

          <section className="panel controls-panel">
            <div className="meta-row">
              <span>最新スキップ理由集計（日次系）</span>
            </div>
            {latestSkipRows.length === 0 ? (
              <p className="muted">集計対象の実行履歴がありません。</p>
            ) : (
              <div className="skip-reason-grid">
                {latestSkipRows.map((row) => (
                  <article key={`${row.job_key}-${row.execution_name}`} className="panel skip-reason-card">
                    <p className="kpi-label">{row.job_label}</p>
                    <p className="muted">execution: {row.execution_name}</p>
                    {row.skip_reason_error && <p className="error-text">{row.skip_reason_error}</p>}
                    {!row.skip_reason_error && row.skip_reasons.length === 0 && (
                      <p className="muted">スキップなし、またはログ未反映です。</p>
                    )}
                    {!row.skip_reason_error && row.skip_reasons.length > 0 && (
                      <ul className="guide-list">
                        {row.skip_reasons.map((reasonRow) => (
                          <li key={reasonRow.reason}>
                            {reasonRow.reason}: {reasonRow.count}件
                          </li>
                        ))}
                      </ul>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="panel table-panel">
            <header className="panel-header">
              <h2>実行履歴（最新）</h2>
            </header>
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>ジョブ</th>
                    <th>Execution</th>
                    <th>状態</th>
                    <th>開始</th>
                    <th>完了</th>
                    <th>メッセージ</th>
                    <th>ログ</th>
                  </tr>
                </thead>
                <tbody>
                  {recentExecutions.length === 0 && (
                    <tr>
                      <td colSpan={7} className="empty-cell">
                        実行履歴はありません。
                      </td>
                    </tr>
                  )}
                  {recentExecutions.map((row) => (
                    <tr key={`${row.job_key}-${row.execution_name}`}>
                      <td>{row.job_label}</td>
                      <td>{row.execution_name}</td>
                      <td className={getExecutionStatusClassName(row.status)}>{formatExecutionStatus(row.status)}</td>
                      <td>{formatTime(row.start_time ?? row.create_time)}</td>
                      <td>{formatTime(row.completion_time)}</td>
                      <td>{row.message ?? '-'}</td>
                      <td>
                        {row.log_uri ? (
                          <a href={row.log_uri} target="_blank" rel="noreferrer">
                            Cloud Logging
                          </a>
                        ) : (
                          '-'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
};

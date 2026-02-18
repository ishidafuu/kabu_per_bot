import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { AppLayout } from '../components/AppLayout';
import { createDashboardClient } from '../lib/api';
import { ApiError, toUserMessage } from '../lib/api/errors';
import type { AdminJobKey, AdminOpsExecution, AdminOpsSummary } from '../types/dashboard';

type VisibleJobKey = Exclude<AdminJobKey, 'backfill'>;

interface JobGuide {
  summary: string;
  schedule: string;
}

const JOB_GUIDES: Record<VisibleJobKey, JobGuide> = {
  daily: {
    summary: '平日18:00想定の日次評価を手動で即時実行します（IMMEDIATE銘柄向け）。',
    schedule: '通常は平日18:00に定期実行',
  },
  daily_at21: {
    summary: '21:05向けの再評価を手動で実行します（AT_21銘柄向け）。',
    schedule: '通常は平日21:05に定期実行',
  },
  earnings_weekly: {
    summary: '来週決算分の通知候補を作成し、今週決算通知を送信します。',
    schedule: '通常は土曜21:00に定期実行',
  },
  earnings_tomorrow: {
    summary: '翌日決算分の通知候補を作成し、明日決算通知を送信します。',
    schedule: '通常は毎日21:00に定期実行',
  },
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

const isVisibleJobKey = (key: AdminJobKey): key is VisibleJobKey => {
  return key !== 'backfill';
};

export const OpsPage = () => {
  const { getIdToken } = useAuth();
  const client = useMemo(() => createDashboardClient({ getToken: getIdToken }), [getIdToken]);
  const [opsSummary, setOpsSummary] = useState<AdminOpsSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [opsError, setOpsError] = useState('');
  const [opsForbidden, setOpsForbidden] = useState(false);
  const [opNotice, setOpNotice] = useState('');
  const [runningJobKey, setRunningJobKey] = useState<VisibleJobKey | 'discord_test' | null>(null);

  const refreshOps = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setOpsError('');
    setOpsForbidden(false);
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
    } finally {
      setIsLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void refreshOps();
  }, [refreshOps]);

  const runJob = useCallback(
    async (jobKey: VisibleJobKey, jobLabel: string): Promise<void> => {
      const guide = JOB_GUIDES[jobKey];
      const accepted = window.confirm(
        `${jobLabel} を実行します。\n\n内容: ${guide.summary}\n通常実行: ${guide.schedule}\n\nこのまま開始しますか？`,
      );
      if (!accepted) {
        return;
      }

      setRunningJobKey(jobKey);
      setOpsError('');
      setOpNotice('');
      try {
        const response = await client.runAdminJob(jobKey);
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
    const accepted = window.confirm(
      'Discord疎通テストを送信します。\n通知チャンネルにテストメッセージが投稿されます。続行しますか？',
    );
    if (!accepted) {
      return;
    }

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

  const jobRows =
    opsSummary?.jobs.filter((row): row is typeof row & { key: VisibleJobKey } => isVisibleJobKey(row.key)) ?? [];
  const recentExecutions: AdminOpsExecution[] = opsSummary?.recent_executions ?? [];
  const latestSkipRows: AdminOpsExecution[] = opsSummary?.latest_skip_reasons ?? [];

  return (
    <AppLayout title="運用操作（管理者）">
      <section className="panel controls-panel">
        <div className="meta-row">
          <span>手動実行メニュー</span>
        </div>
        <p className="muted">
          定期実行の代替や障害時の再実行を行う画面です。通常運用では定期実行に任せ、必要時のみ手動実行してください。
        </p>
        <div className="inline-actions">
          <button type="button" className="secondary" onClick={() => void refreshOps()} disabled={isLoading}>
            {isLoading ? '読込中...' : '運用情報を更新'}
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
        {opsForbidden && (
          <p className="error-text">
            管理者権限がないため表示できません。API側の `API_ADMIN_UIDS` か Firebase カスタムクレーム `admin=true`
            を確認してください。
          </p>
        )}
        {opsError && <p className="error-text">{opsError}</p>}
        {opNotice && <p className="notice-text">{opNotice}</p>}
      </section>

      {!opsForbidden && (
        <>
          <section className="panel table-panel">
            <header className="panel-header">
              <h2>ジョブ説明と実行</h2>
            </header>
            <div className="table-wrapper">
              <table className="ops-job-table">
                <thead>
                  <tr>
                    <th>ジョブ</th>
                    <th>通常スケジュール</th>
                    <th>何をするか</th>
                    <th>設定</th>
                    <th>実行</th>
                  </tr>
                </thead>
                <tbody>
                  {jobRows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="empty-cell">
                        実行対象ジョブがありません。
                      </td>
                    </tr>
                  )}
                  {jobRows.map((row) => {
                    const guide = JOB_GUIDES[row.key];
                    return (
                      <tr key={row.key}>
                        <td>{row.label}</td>
                        <td>{guide.schedule}</td>
                        <td>{guide.summary}</td>
                        <td>{row.job_name ?? '未設定'}</td>
                        <td>
                          <button
                            type="button"
                            className="primary"
                            disabled={!row.configured || runningJobKey !== null}
                            onClick={() => void runJob(row.key, row.label)}
                          >
                            {runningJobKey === row.key ? '実行中...' : '実行'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
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
    </AppLayout>
  );
};

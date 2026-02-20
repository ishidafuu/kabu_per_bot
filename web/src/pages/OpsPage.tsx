import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { AppLayout } from '../components/AppLayout';
import { createDashboardClient } from '../lib/api';
import { appConfig } from '../lib/config';
import { ApiError, toUserMessage } from '../lib/api/errors';
import type { AdminGlobalSettings, AdminJobKey, AdminOpsExecution, AdminOpsSummary } from '../types/dashboard';

type VisibleJobKey = Exclude<AdminJobKey, 'backfill'>;
type OpsSectionKey = 'settings' | 'manual' | 'skip' | 'history';

interface JobGuide {
  summary: string;
  schedule: string;
}

const HISTORY_LIMIT_PER_JOB = 20;

const OPS_SECTIONS: ReadonlyArray<{ key: OpsSectionKey; label: string }> = [
  { key: 'settings', label: '通知・Grok設定' },
  { key: 'manual', label: '手動実行' },
  { key: 'skip', label: 'スキップ集計' },
  { key: 'history', label: '実行履歴' },
];

const JOB_GUIDES: Record<VisibleJobKey, JobGuide> = {
  immediate_open: {
    summary: '寄り付き帯（IMMEDIATE）を手動実行します。設定した時間帯・間隔に一致する時刻のみ判定します。',
    schedule: '通常は平日8:00-11:59に毎分起動（設定条件に合う時刻のみ実処理）',
  },
  immediate_close: {
    summary: '引け帯（IMMEDIATE）を手動実行します。設定した時間帯・間隔に一致する時刻のみ判定します。',
    schedule: '通常は平日13:00-16:59に毎分起動（設定条件に合う時刻のみ実処理）',
  },
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

const formatGrokBalance = (settings: AdminGlobalSettings | null, isLoading: boolean): string => {
  if (settings == null) {
    return isLoading ? '読込中...' : '未取得';
  }
  const balance = settings.grok_balance;
  if (!balance.configured) {
    return '未設定（GROK_MANAGEMENT_API_KEY / GROK_MANAGEMENT_TEAM_ID）';
  }
  if (!balance.available || balance.amount == null) {
    return `取得失敗${balance.error ? `: ${balance.error}` : ''}`;
  }
  const amountText = balance.amount.toLocaleString('ja-JP', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  });
  return `${amountText}${balance.currency ? ` ${balance.currency}` : ''}`;
};

const isVisibleJobKey = (key: AdminJobKey): key is VisibleJobKey => {
  return key !== 'backfill';
};

const getHistoryPageLabel = (index: number): number => {
  return index + 1;
};

export const OpsPage = () => {
  const { getIdToken } = useAuth();
  const client = useMemo(() => createDashboardClient({ getToken: getIdToken }), [getIdToken]);
  const [activeSection, setActiveSection] = useState<OpsSectionKey>('settings');
  const [opsSummary, setOpsSummary] = useState<AdminOpsSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [opsError, setOpsError] = useState('');
  const [opsForbidden, setOpsForbidden] = useState(false);
  const [opNotice, setOpNotice] = useState('');
  const [runningJobKey, setRunningJobKey] = useState<VisibleJobKey | 'discord_test' | 'grok_cooldown_reset' | null>(null);
  const [globalSettings, setGlobalSettings] = useState<AdminGlobalSettings | null>(null);
  const [cooldownHoursInput, setCooldownHoursInput] = useState('');
  const [intelNotificationMaxAgeDaysInput, setIntelNotificationMaxAgeDaysInput] = useState('30');
  const [scheduleEnabledInput, setScheduleEnabledInput] = useState(true);
  const [openWindowStartInput, setOpenWindowStartInput] = useState('09:00');
  const [openWindowEndInput, setOpenWindowEndInput] = useState('10:00');
  const [openWindowIntervalInput, setOpenWindowIntervalInput] = useState('15');
  const [closeWindowStartInput, setCloseWindowStartInput] = useState('14:30');
  const [closeWindowEndInput, setCloseWindowEndInput] = useState('15:30');
  const [closeWindowIntervalInput, setCloseWindowIntervalInput] = useState('10');
  const [grokSnsEnabledInput, setGrokSnsEnabledInput] = useState(false);
  const [grokScheduledTimeInput, setGrokScheduledTimeInput] = useState('21:10');
  const [grokCooldownHoursInput, setGrokCooldownHoursInput] = useState('24');
  const [grokPromptTemplateInput, setGrokPromptTemplateInput] = useState('');
  const [isSavingGlobalSettings, setIsSavingGlobalSettings] = useState(false);
  const [historyPageIndex, setHistoryPageIndex] = useState(0);

  const applyGlobalSettings = useCallback((value: AdminGlobalSettings): void => {
    setGlobalSettings(value);
    setCooldownHoursInput(String(value.cooldown_hours));
    setIntelNotificationMaxAgeDaysInput(String(value.intel_notification_max_age_days));
    setScheduleEnabledInput(value.immediate_schedule.enabled);
    setOpenWindowStartInput(value.immediate_schedule.open_window_start);
    setOpenWindowEndInput(value.immediate_schedule.open_window_end);
    setOpenWindowIntervalInput(String(value.immediate_schedule.open_window_interval_min));
    setCloseWindowStartInput(value.immediate_schedule.close_window_start);
    setCloseWindowEndInput(value.immediate_schedule.close_window_end);
    setCloseWindowIntervalInput(String(value.immediate_schedule.close_window_interval_min));
    setGrokSnsEnabledInput(value.grok_sns.enabled);
    setGrokScheduledTimeInput(value.grok_sns.scheduled_time);
    setGrokCooldownHoursInput(String(value.grok_sns.per_ticker_cooldown_hours));
    setGrokPromptTemplateInput(value.grok_sns.prompt_template);
  }, []);

  const refreshOps = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setOpsError('');
    setOpsForbidden(false);
    try {
      if (activeSection === 'settings') {
        const settingsResponse = await client.getAdminGlobalSettings();
        applyGlobalSettings(settingsResponse);
        setOpsSummary(null);
      } else {
        let summaryPromise: Promise<AdminOpsSummary>;
        if (activeSection === 'manual') {
          summaryPromise = client.getAdminOpsSummary({
            includeRecentExecutions: false,
            includeSkipReasons: false,
          });
        } else if (activeSection === 'skip') {
          summaryPromise = client.getAdminOpsSummary({
            limitPerJob: 1,
            includeRecentExecutions: false,
            includeSkipReasons: true,
          });
        } else {
          summaryPromise = client.getAdminOpsSummary({
            limitPerJob: HISTORY_LIMIT_PER_JOB,
            includeRecentExecutions: true,
            includeSkipReasons: false,
          });
        }
        const [settingsResult, summaryResult] = await Promise.allSettled([client.getAdminGlobalSettings(), summaryPromise]);
        if (settingsResult.status === 'fulfilled') {
          applyGlobalSettings(settingsResult.value);
        }
        if (summaryResult.status === 'rejected') {
          throw summaryResult.reason;
        }
        setOpsSummary(summaryResult.value);
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        setOpsForbidden(true);
        setOpsSummary(null);
        setGlobalSettings(null);
        return;
      }
      setOpsError(toUserMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, [activeSection, applyGlobalSettings, client]);

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

  const resetGrokCooldown = useCallback(async (): Promise<void> => {
    const accepted = window.confirm(
      'Grokの再取得抑制をリセットします。\nSNS注目の通知ログと既読キャッシュを削除し、次回定時で再通知可能にします。続行しますか？',
    );
    if (!accepted) {
      return;
    }

    setRunningJobKey('grok_cooldown_reset');
    setOpsError('');
    setOpNotice('');
    try {
      const response = await client.resetGrokCooldown();
      setOpNotice(
        `Grok再取得リセット完了: 通知ログ${response.deleted_notification_logs}件 + 既読${response.deleted_seen_entries}件（合計${response.deleted_entries}件, ${formatTime(response.reset_at)}）`,
      );
      await refreshOps();
    } catch (error) {
      setOpsError(toUserMessage(error));
    } finally {
      setRunningJobKey(null);
    }
  }, [client, refreshOps]);

  const saveGlobalSettings = useCallback(async (): Promise<void> => {
    const rawValue = cooldownHoursInput.trim();
    const parsed = Number(rawValue);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      setOpsError('クールダウン時間は1以上の整数で入力してください。');
      return;
    }
    const intelMaxAgeDays = Number(intelNotificationMaxAgeDaysInput.trim());
    if (!Number.isInteger(intelMaxAgeDays) || intelMaxAgeDays <= 0) {
      setOpsError('IR/SNS通知対象期間は1以上の整数で入力してください。');
      return;
    }
    const hhmm = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
    if (!hhmm.test(openWindowStartInput) || !hhmm.test(openWindowEndInput)) {
      setOpsError('寄り付き帯の時刻は HH:MM 形式で入力してください。');
      return;
    }
    if (!hhmm.test(closeWindowStartInput) || !hhmm.test(closeWindowEndInput)) {
      setOpsError('引け帯の時刻は HH:MM 形式で入力してください。');
      return;
    }
    if (!hhmm.test(grokScheduledTimeInput)) {
      setOpsError('Grok定時取得時刻は HH:MM 形式で入力してください。');
      return;
    }
    const openInterval = Number(openWindowIntervalInput.trim());
    const closeInterval = Number(closeWindowIntervalInput.trim());
    const grokCooldownHours = Number(grokCooldownHoursInput.trim());
    if (!Number.isInteger(openInterval) || openInterval < 1 || openInterval > 60) {
      setOpsError('寄り付き帯の間隔は1〜60の整数で入力してください。');
      return;
    }
    if (!Number.isInteger(closeInterval) || closeInterval < 1 || closeInterval > 60) {
      setOpsError('引け帯の間隔は1〜60の整数で入力してください。');
      return;
    }
    if (!Number.isInteger(grokCooldownHours) || grokCooldownHours < 1 || grokCooldownHours > 168) {
      setOpsError('Grokの再取得間隔は1〜168の整数で入力してください。');
      return;
    }
    if (grokPromptTemplateInput.trim().length < 20) {
      setOpsError('Grokプロンプトは20文字以上で入力してください。');
      return;
    }

    setIsSavingGlobalSettings(true);
    setOpsError('');
    setOpNotice('');
    try {
      const response = await client.updateAdminGlobalSettings({
        cooldown_hours: parsed,
        intel_notification_max_age_days: intelMaxAgeDays,
        immediate_schedule: {
          enabled: scheduleEnabledInput,
          open_window_start: openWindowStartInput,
          open_window_end: openWindowEndInput,
          open_window_interval_min: openInterval,
          close_window_start: closeWindowStartInput,
          close_window_end: closeWindowEndInput,
          close_window_interval_min: closeInterval,
        },
        grok_sns: {
          enabled: grokSnsEnabledInput,
          scheduled_time: grokScheduledTimeInput,
          per_ticker_cooldown_hours: grokCooldownHours,
          prompt_template: grokPromptTemplateInput.trim(),
        },
      });
      applyGlobalSettings(response);
      setOpNotice(`全体設定を更新しました（クールダウン: ${response.cooldown_hours}時間）。`);
    } catch (error) {
      setOpsError(toUserMessage(error));
    } finally {
      setIsSavingGlobalSettings(false);
    }
  }, [
    applyGlobalSettings,
    client,
    closeWindowEndInput,
    closeWindowIntervalInput,
    closeWindowStartInput,
    cooldownHoursInput,
    intelNotificationMaxAgeDaysInput,
    grokCooldownHoursInput,
    grokPromptTemplateInput,
    grokScheduledTimeInput,
    grokSnsEnabledInput,
    openWindowEndInput,
    openWindowIntervalInput,
    openWindowStartInput,
    scheduleEnabledInput,
  ]);

  const jobRows =
    opsSummary?.jobs.filter((row): row is typeof row & { key: VisibleJobKey } => isVisibleJobKey(row.key)) ?? [];
  const recentExecutions: AdminOpsExecution[] = opsSummary?.recent_executions ?? [];
  const latestSkipRows: AdminOpsExecution[] = opsSummary?.latest_skip_reasons ?? [];
  const historyPageSize = appConfig.pageSize;
  const historyPageCount = Math.max(Math.ceil(recentExecutions.length / historyPageSize), 1);
  const normalizedHistoryPage = Math.min(historyPageIndex, historyPageCount - 1);
  const historyOffset = normalizedHistoryPage * historyPageSize;
  const pagedRecentExecutions = recentExecutions.slice(historyOffset, historyOffset + historyPageSize);
  const canGoHistoryPrev = normalizedHistoryPage > 0;
  const canGoHistoryNext = normalizedHistoryPage + 1 < historyPageCount;

  return (
    <AppLayout title="運用操作（管理者）">
      <section className="panel controls-panel">
        <div className="meta-row">
          <span>運用メニュー</span>
        </div>
        <div className="ops-subnav">
          {OPS_SECTIONS.map((section) => (
            <button
              key={section.key}
              type="button"
              className={`ghost ops-subnav-button${activeSection === section.key ? ' active' : ''}`}
              onClick={() => {
                setActiveSection(section.key);
                setHistoryPageIndex(0);
              }}
              disabled={isLoading}
            >
              {section.label}
            </button>
          ))}
        </div>
        <p className="muted">🧭 表示中メニューのみ読み込むため、初期表示の負荷を抑えています。</p>
        <div className="inline-actions">
          <button type="button" className="secondary" onClick={() => void refreshOps()} disabled={isLoading}>
            {isLoading ? '読込中...' : '表示中メニューを更新'}
          </button>
          {activeSection === 'manual' && (
            <button
              type="button"
              className="secondary"
              onClick={() => void sendDiscordTest()}
              disabled={runningJobKey !== null || opsForbidden}
            >
              {runningJobKey === 'discord_test' ? '送信中...' : 'Discord疎通テスト'}
            </button>
          )}
        </div>
      </section>

      {opsForbidden && (
        <section className="panel controls-panel">
          <p className="error-text">
            管理者権限がないため表示できません。API側の `API_ADMIN_UIDS` か Firebase カスタムクレーム `admin=true`
            を確認してください。
          </p>
        </section>
      )}
      {opsError && <p className="error-text">{opsError}</p>}
      {opNotice && <p className="notice-text">{opNotice}</p>}

      {!opsForbidden && activeSection === 'settings' && (
        <section className="panel controls-panel">
          <div className="meta-row">
            <span>全体設定（通知）</span>
          </div>
          <p className="muted">
            同一条件通知のクールダウン時間を設定します。通常→強への昇格通知はクールダウン内でも即時通知されます。
          </p>
          <p className="muted">
            あわせてIMMEDIATEの寄り付き帯/引け帯の実行時間帯と間隔（分）を設定できます。タイムゾーンはJST固定です。
          </p>
          <p className="muted">GrokによるSNS取得の定時時刻・再取得間隔・プロンプトテンプレートもここで設定できます。</p>
          <p className="muted">
            Grok残高: {formatGrokBalance(globalSettings, isLoading)}
            {globalSettings?.grok_balance.fetched_at ? `（${formatTime(globalSettings.grok_balance.fetched_at)} 取得）` : ''}
          </p>
          <p className="muted">IR/SNS通知は初回実行時のみ既読化し、公開日が対象期間内のものだけ通知されます。</p>
          <div className="settings-inline">
            <label className="inline-field">
              クールダウン（時間）
              <input
                type="number"
                min={1}
                step={1}
                value={cooldownHoursInput}
                onChange={(event) => setCooldownHoursInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
            <label className="inline-field">
              IR/SNS通知対象期間（日）
              <input
                type="number"
                min={1}
                step={1}
                value={intelNotificationMaxAgeDaysInput}
                onChange={(event) => setIntelNotificationMaxAgeDaysInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
            <label className="inline-checkbox">
              <input
                type="checkbox"
                checked={scheduleEnabledInput}
                onChange={(event) => setScheduleEnabledInput(event.target.checked)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
              IMMEDIATE帯設定を有効化
            </label>
          </div>
          <div className="settings-inline">
            <label className="inline-field">
              寄り付き帯 開始（HH:MM）
              <input
                type="text"
                value={openWindowStartInput}
                onChange={(event) => setOpenWindowStartInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
            <label className="inline-field">
              寄り付き帯 終了（HH:MM）
              <input
                type="text"
                value={openWindowEndInput}
                onChange={(event) => setOpenWindowEndInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
            <label className="inline-field">
              寄り付き帯 間隔（分）
              <input
                type="number"
                min={1}
                max={60}
                step={1}
                value={openWindowIntervalInput}
                onChange={(event) => setOpenWindowIntervalInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
          </div>
          <div className="settings-inline">
            <label className="inline-field">
              引け帯 開始（HH:MM）
              <input
                type="text"
                value={closeWindowStartInput}
                onChange={(event) => setCloseWindowStartInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
            <label className="inline-field">
              引け帯 終了（HH:MM）
              <input
                type="text"
                value={closeWindowEndInput}
                onChange={(event) => setCloseWindowEndInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
            <label className="inline-field">
              引け帯 間隔（分）
              <input
                type="number"
                min={1}
                max={60}
                step={1}
                value={closeWindowIntervalInput}
                onChange={(event) => setCloseWindowIntervalInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
          </div>
          <div className="settings-inline">
            <label className="inline-checkbox">
              <input
                type="checkbox"
                checked={grokSnsEnabledInput}
                onChange={(event) => setGrokSnsEnabledInput(event.target.checked)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
              Grok SNS取得を有効化
            </label>
            <label className="inline-field">
              Grok定時取得（HH:MM JST）
              <input
                type="text"
                value={grokScheduledTimeInput}
                onChange={(event) => setGrokScheduledTimeInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
            <label className="inline-field">
              1銘柄ごとの再取得間隔（時間）
              <input
                type="number"
                min={1}
                max={168}
                step={1}
                value={grokCooldownHoursInput}
                onChange={(event) => setGrokCooldownHoursInput(event.target.value)}
                disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              />
            </label>
          </div>
          <label>
            Grokへ渡すプロンプトテンプレート
            <textarea
              value={grokPromptTemplateInput}
              onChange={(event) => setGrokPromptTemplateInput(event.target.value)}
              disabled={opsForbidden || isSavingGlobalSettings || isLoading}
              rows={6}
            />
          </label>
          <div className="settings-inline">
            <button
              type="button"
              className="secondary"
              onClick={() => void resetGrokCooldown()}
              disabled={opsForbidden || isLoading || isSavingGlobalSettings || runningJobKey !== null}
            >
              {runningJobKey === 'grok_cooldown_reset' ? 'リセット中...' : 'Grokクールダウン全解除'}
            </button>
          </div>
          <p className="muted">
            Grokの再取得確認が必要な場合に使用します。`SNS注目` の通知ログを削除し、次回定時で再取得可能にします。
          </p>
          <div className="settings-inline">
            <button
              type="button"
              className="primary"
              onClick={() => void saveGlobalSettings()}
              disabled={opsForbidden || isSavingGlobalSettings || isLoading}
            >
              {isSavingGlobalSettings ? '保存中...' : '設定を保存'}
            </button>
          </div>
          <p className="muted">
            現在値: {globalSettings ? `${globalSettings.cooldown_hours}時間` : '-'} / 反映元:{' '}
            {globalSettings?.source === 'firestore' ? '管理画面設定' : '環境変数デフォルト'}
          </p>
          {globalSettings && (
            <p className="muted">IR/SNS通知対象期間: {globalSettings.intel_notification_max_age_days}日</p>
          )}
          {globalSettings && (
            <p className="muted">
              IMMEDIATE帯: {globalSettings.immediate_schedule.enabled ? '有効' : '無効'} / 寄り付き{' '}
              {globalSettings.immediate_schedule.open_window_start}-{globalSettings.immediate_schedule.open_window_end} (
              {globalSettings.immediate_schedule.open_window_interval_min}分) / 引け{' '}
              {globalSettings.immediate_schedule.close_window_start}-{globalSettings.immediate_schedule.close_window_end} (
              {globalSettings.immediate_schedule.close_window_interval_min}分)
            </p>
          )}
          {globalSettings && (
            <p className="muted">
              Grok SNS: {globalSettings.grok_sns.enabled ? '有効' : '無効'} / 定時 {globalSettings.grok_sns.scheduled_time} /
              再取得間隔 {globalSettings.grok_sns.per_ticker_cooldown_hours}時間
            </p>
          )}
          {globalSettings?.updated_at && (
            <p className="muted">
              最終更新: {formatTime(globalSettings.updated_at)}（{globalSettings.updated_by ?? 'unknown'}）
            </p>
          )}
        </section>
      )}

      {!opsForbidden && activeSection === 'manual' && (
        <>
          <section className="panel controls-panel">
            <div className="meta-row">
              <span>手動実行メニュー</span>
            </div>
            <p className="muted">
              ▶️ 定期実行の代替や障害時の再実行を行う画面です。通常運用では定期実行に任せ、必要時のみ手動実行してください。
            </p>
          </section>
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
                  {isLoading && jobRows.length === 0 && (
                    <tr>
                      <td colSpan={5} className="empty-cell">
                        読み込み中...
                      </td>
                    </tr>
                  )}
                  {!isLoading && jobRows.length === 0 && (
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
                            disabled={!row.configured || runningJobKey !== null || isLoading}
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
        </>
      )}

      {!opsForbidden && activeSection === 'skip' && (
        <section className="panel controls-panel">
          <div className="meta-row">
            <span>最新スキップ理由集計（日次・IMMEDIATE系）</span>
          </div>
          <p className="muted">📉 Cloud Logging解析は重いため、このタブを開いた時のみ取得します。</p>
          {isLoading && latestSkipRows.length === 0 && <p className="muted">読み込み中...</p>}
          {!isLoading && latestSkipRows.length === 0 ? (
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
      )}

      {!opsForbidden && activeSection === 'history' && (
        <>
          <section className="panel controls-panel">
            <div className="meta-row">
              <span>実行履歴（ページ分割表示）</span>
              <span>表示件数: {historyPageSize}</span>
              <span>ページ: {getHistoryPageLabel(normalizedHistoryPage)}</span>
            </div>
          </section>
          <section className="panel table-panel">
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
                  {isLoading && pagedRecentExecutions.length === 0 && (
                    <tr>
                      <td colSpan={7} className="empty-cell">
                        読み込み中...
                      </td>
                    </tr>
                  )}
                  {!isLoading && pagedRecentExecutions.length === 0 && (
                    <tr>
                      <td colSpan={7} className="empty-cell">
                        実行履歴はありません。
                      </td>
                    </tr>
                  )}
                  {pagedRecentExecutions.map((row) => (
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
            <div className="pagination-row">
              <button
                type="button"
                className="ghost"
                disabled={!canGoHistoryPrev || isLoading}
                onClick={() => {
                  setHistoryPageIndex((prev) => Math.max(prev - 1, 0));
                }}
              >
                前へ
              </button>
              <button
                type="button"
                className="ghost"
                disabled={!canGoHistoryNext || isLoading}
                onClick={() => {
                  setHistoryPageIndex((prev) => prev + 1);
                }}
              >
                次へ
              </button>
            </div>
          </section>
        </>
      )}
    </AppLayout>
  );
};

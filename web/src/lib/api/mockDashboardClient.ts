import type {
  AdminGrokCooldownResetResponse,
  AdminGlobalSettings,
  AdminGlobalSettingsUpdatePayload,
  AdminJobKey,
  AdminOpsExecution,
  AdminOpsSummary,
  AdminOpsJob,
  BackfillRunPayload,
  DashboardSummary,
  RunAdminJobResponse,
} from '../../types/dashboard';
import { getMockWatchlistCount } from './mockWatchlistClient';
import type { DashboardClient, GetAdminOpsSummaryParams } from './dashboardClient';

const wait = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

const seedSummary: DashboardSummary = {
  watchlist_count: 12,
  today_notification_count: 5,
  today_data_unknown_count: 1,
  failed_job_exists: false,
};

let mockExecutionSeq = 1;
const mockJobs: AdminOpsJob[] = [
  { key: 'immediate_open', label: '寄り付き帯ジョブ（IMMEDIATE）', job_name: 'kabu-immediate-open', configured: true },
  { key: 'immediate_close', label: '引け帯ジョブ（IMMEDIATE）', job_name: 'kabu-immediate-close', configured: true },
  { key: 'daily', label: '日次ジョブ（IMMEDIATE）', job_name: 'kabu-daily', configured: true },
  { key: 'daily_at21', label: '21:05ジョブ（AT_21）', job_name: 'kabu-daily-at21', configured: true },
  { key: 'earnings_weekly', label: '今週決算ジョブ', job_name: 'kabu-earnings-weekly', configured: true },
  { key: 'earnings_tomorrow', label: '明日決算ジョブ', job_name: 'kabu-earnings-tomorrow', configured: true },
  { key: 'backfill', label: 'バックフィルジョブ', job_name: null, configured: false },
];

const mockRecentExecutions: AdminOpsExecution[] = [];
let mockGlobalSettings: AdminGlobalSettings = {
  cooldown_hours: 2,
  intel_notification_max_age_days: 30,
  immediate_schedule: {
    enabled: true,
    timezone: 'Asia/Tokyo',
    open_window_start: '09:00',
    open_window_end: '10:00',
    open_window_interval_min: 15,
    close_window_start: '14:30',
    close_window_end: '15:30',
    close_window_interval_min: 10,
  },
  grok_sns: {
    enabled: false,
    scheduled_time: '21:10',
    per_ticker_cooldown_hours: 24,
    prompt_template:
      '以下の銘柄に関連する直近のSNS投稿を要約してください。重要度が高い話題を優先し、投稿者・時刻・URLを必ず含めてください。',
  },
  grok_balance: {
    configured: false,
    available: false,
    amount: null,
    currency: null,
    fetched_at: null,
    error: 'GROK_MANAGEMENT_API_KEY または GROK_MANAGEMENT_TEAM_ID が未設定です。',
  },
  source: 'env_default',
  updated_at: null,
  updated_by: null,
};

const appendExecution = (jobKey: AdminJobKey): AdminOpsExecution => {
  const job = mockJobs.find((row) => row.key === jobKey);
  if (!job || !job.job_name) {
    throw new Error('job is not configured');
  }
  const now = new Date().toISOString();
  const execution: AdminOpsExecution = {
    job_key: job.key,
    job_label: job.label,
    job_name: job.job_name,
    execution_name: `${job.job_name}-mock-${mockExecutionSeq}`,
    status: 'SUCCEEDED',
    create_time: now,
    start_time: now,
    completion_time: now,
    message: 'Execution completed successfully.',
    log_uri: 'https://example.com/mock-log',
    skip_reasons: jobKey === 'daily_at21' ? [{ reason: '2時間クールダウン中', count: 4 }] : [],
    skip_reason_error: null,
  };
  mockExecutionSeq += 1;
  mockRecentExecutions.unshift(execution);
  if (mockRecentExecutions.length > 20) {
    mockRecentExecutions.pop();
  }
  return execution;
};

export class MockDashboardClient implements DashboardClient {
  async getSummary(): Promise<DashboardSummary> {
    await wait(120);
    return {
      ...seedSummary,
      watchlist_count: getMockWatchlistCount(),
    };
  }

  async getAdminOpsSummary(params: GetAdminOpsSummaryParams = {}): Promise<AdminOpsSummary> {
    const includeRecentExecutions = params.includeRecentExecutions ?? true;
    const includeSkipReasons = params.includeSkipReasons ?? true;
    const limitPerJob = params.limitPerJob ?? 5;
    const recentLimit = Math.max(limitPerJob, 1) * mockJobs.filter((row) => row.configured).length;

    await wait(80);
    return {
      jobs: mockJobs,
      recent_executions: includeRecentExecutions ? mockRecentExecutions.slice(0, recentLimit) : [],
      latest_skip_reasons: includeSkipReasons
        ? mockRecentExecutions
            .filter(
              (row) =>
                row.job_key === 'immediate_open' ||
                row.job_key === 'immediate_close' ||
                row.job_key === 'daily' ||
                row.job_key === 'daily_at21',
            )
            .slice(0, 2)
        : [],
    };
  }

  async runAdminJob(jobKey: AdminJobKey, payload?: BackfillRunPayload): Promise<RunAdminJobResponse> {
    await wait(120);
    if (jobKey === 'backfill' && payload == null) {
      throw new Error('backfill payload is required');
    }
    return { execution: appendExecution(jobKey) };
  }

  async listAdminExecutions(jobKey: AdminJobKey, limit = 20): Promise<AdminOpsExecution[]> {
    await wait(60);
    return mockRecentExecutions.filter((row) => row.job_key === jobKey).slice(0, limit);
  }

  async sendDiscordTest(): Promise<{ sent_at: string }> {
    await wait(60);
    return { sent_at: new Date().toISOString() };
  }

  async resetGrokCooldown(ticker?: string): Promise<AdminGrokCooldownResetResponse> {
    await wait(80);
    const deletedNotificationLogs = ticker ? 3 : 12;
    const deletedSeenEntries = ticker ? 2 : 8;
    return {
      reset_at: new Date().toISOString(),
      deleted_entries: deletedNotificationLogs + deletedSeenEntries,
      deleted_notification_logs: deletedNotificationLogs,
      deleted_seen_entries: deletedSeenEntries,
      ticker: ticker ?? null,
    };
  }

  async getAdminGlobalSettings(): Promise<AdminGlobalSettings> {
    await wait(60);
    return mockGlobalSettings;
  }

  async updateAdminGlobalSettings(payload: AdminGlobalSettingsUpdatePayload): Promise<AdminGlobalSettings> {
    await wait(80);
    mockGlobalSettings = {
      cooldown_hours: payload.cooldown_hours ?? mockGlobalSettings.cooldown_hours,
      intel_notification_max_age_days:
        payload.intel_notification_max_age_days ?? mockGlobalSettings.intel_notification_max_age_days,
      immediate_schedule: payload.immediate_schedule
        ? {
            timezone: 'Asia/Tokyo',
            ...payload.immediate_schedule,
          }
        : mockGlobalSettings.immediate_schedule,
      grok_sns: payload.grok_sns
        ? {
            ...payload.grok_sns,
          }
        : mockGlobalSettings.grok_sns,
      grok_balance: mockGlobalSettings.grok_balance,
      source: 'firestore',
      updated_at: new Date().toISOString(),
      updated_by: 'mock-admin',
    };
    return mockGlobalSettings;
  }
}

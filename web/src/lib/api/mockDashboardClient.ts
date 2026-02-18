import type {
  AdminJobKey,
  AdminOpsExecution,
  AdminOpsSummary,
  BackfillRunPayload,
  DashboardSummary,
  RunAdminJobResponse,
} from '../../types/dashboard';
import { getMockWatchlistCount } from './mockWatchlistClient';
import type { DashboardClient } from './dashboardClient';

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
const mockJobs: AdminOpsSummary['jobs'] = [
  { key: 'daily', label: '日次ジョブ（IMMEDIATE）', job_name: 'kabu-daily', configured: true },
  { key: 'daily_at21', label: '21:05ジョブ（AT_21）', job_name: 'kabu-daily-at21', configured: true },
  { key: 'earnings_weekly', label: '今週決算ジョブ', job_name: 'kabu-earnings-weekly', configured: true },
  { key: 'earnings_tomorrow', label: '明日決算ジョブ', job_name: 'kabu-earnings-tomorrow', configured: true },
  { key: 'backfill', label: 'バックフィルジョブ', job_name: null, configured: false },
];

const mockRecentExecutions: AdminOpsExecution[] = [];

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

  async getAdminOpsSummary(): Promise<AdminOpsSummary> {
    await wait(80);
    return {
      jobs: mockJobs,
      recent_executions: mockRecentExecutions,
      latest_skip_reasons: mockRecentExecutions
        .filter((row) => row.job_key === 'daily' || row.job_key === 'daily_at21')
        .slice(0, 2),
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
}

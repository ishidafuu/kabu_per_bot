import type {
  AdminGrokCooldownResetResponse,
  AdminGlobalSettings,
  AdminGlobalSettingsUpdatePayload,
  AdminJobKey,
  AdminOpsExecution,
  AdminOpsSummary,
  BackfillRunPayload,
  DashboardSummary,
  RunMissingTechnicalResponse,
  RunAdminJobResponse,
} from '../../types/dashboard';
import { HttpClient } from './httpClient';

export interface GetAdminOpsSummaryParams {
  limitPerJob?: number;
  includeRecentExecutions?: boolean;
  includeSkipReasons?: boolean;
}

export interface DashboardClient {
  getSummary(): Promise<DashboardSummary>;
  getAdminOpsSummary(params?: GetAdminOpsSummaryParams): Promise<AdminOpsSummary>;
  getAdminGlobalSettings(): Promise<AdminGlobalSettings>;
  updateAdminGlobalSettings(payload: AdminGlobalSettingsUpdatePayload): Promise<AdminGlobalSettings>;
  runAdminJob(jobKey: AdminJobKey, payload?: BackfillRunPayload): Promise<RunAdminJobResponse>;
  runMissingTechnicalLatest(): Promise<RunMissingTechnicalResponse>;
  listAdminExecutions(jobKey: AdminJobKey, limit?: number): Promise<AdminOpsExecution[]>;
  sendDiscordTest(): Promise<{ sent_at: string }>;
  resetGrokCooldown(ticker?: string): Promise<AdminGrokCooldownResetResponse>;
}

export class HttpDashboardClient implements DashboardClient {
  private readonly httpClient: HttpClient;

  constructor(httpClient: HttpClient) {
    this.httpClient = httpClient;
  }

  async getSummary(): Promise<DashboardSummary> {
    return this.httpClient.request<DashboardSummary>('/dashboard/summary', {
      method: 'GET',
    });
  }

  async getAdminOpsSummary(params: GetAdminOpsSummaryParams = {}): Promise<AdminOpsSummary> {
    const query = new URLSearchParams();

    if (params.limitPerJob != null) {
      query.set('limit_per_job', String(params.limitPerJob));
    }
    if (params.includeRecentExecutions != null) {
      query.set('include_recent_executions', String(params.includeRecentExecutions));
    }
    if (params.includeSkipReasons != null) {
      query.set('include_skip_reasons', String(params.includeSkipReasons));
    }

    const suffix = query.toString();
    const path = suffix.length > 0 ? `/admin/ops/summary?${suffix}` : '/admin/ops/summary';

    return this.httpClient.request<AdminOpsSummary>(path, {
      method: 'GET',
    });
  }

  async runAdminJob(jobKey: AdminJobKey, payload?: BackfillRunPayload): Promise<RunAdminJobResponse> {
    return this.httpClient.request<RunAdminJobResponse>(`/admin/ops/jobs/${jobKey}/run`, {
      method: 'POST',
      body: payload ? JSON.stringify(payload) : undefined,
    });
  }

  async runMissingTechnicalLatest(): Promise<RunMissingTechnicalResponse> {
    return this.httpClient.request<RunMissingTechnicalResponse>('/admin/ops/technical/missing-latest/run', {
      method: 'POST',
    });
  }

  async listAdminExecutions(jobKey: AdminJobKey, limit = 20): Promise<AdminOpsExecution[]> {
    const response = await this.httpClient.request<{ items: AdminOpsExecution[] }>(
      `/admin/ops/jobs/${jobKey}/executions?limit=${limit}`,
      {
        method: 'GET',
      },
    );
    return response.items;
  }

  async sendDiscordTest(): Promise<{ sent_at: string }> {
    return this.httpClient.request<{ sent_at: string }>('/admin/ops/discord/test', {
      method: 'POST',
    });
  }

  async resetGrokCooldown(ticker?: string): Promise<AdminGrokCooldownResetResponse> {
    const suffix = ticker != null && ticker.trim().length > 0 ? `?ticker=${encodeURIComponent(ticker.trim())}` : '';
    return this.httpClient.request<AdminGrokCooldownResetResponse>(`/admin/ops/grok/cooldown/reset${suffix}`, {
      method: 'POST',
    });
  }

  async getAdminGlobalSettings(): Promise<AdminGlobalSettings> {
    return this.httpClient.request<AdminGlobalSettings>('/admin/settings/global', {
      method: 'GET',
    });
  }

  async updateAdminGlobalSettings(payload: AdminGlobalSettingsUpdatePayload): Promise<AdminGlobalSettings> {
    return this.httpClient.request<AdminGlobalSettings>('/admin/settings/global', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }
}

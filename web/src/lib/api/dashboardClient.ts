import type {
  AdminJobKey,
  AdminOpsExecution,
  AdminOpsSummary,
  BackfillRunPayload,
  DashboardSummary,
  RunAdminJobResponse,
} from '../../types/dashboard';
import { HttpClient } from './httpClient';

export interface DashboardClient {
  getSummary(): Promise<DashboardSummary>;
  getAdminOpsSummary(): Promise<AdminOpsSummary>;
  runAdminJob(jobKey: AdminJobKey, payload?: BackfillRunPayload): Promise<RunAdminJobResponse>;
  listAdminExecutions(jobKey: AdminJobKey, limit?: number): Promise<AdminOpsExecution[]>;
  sendDiscordTest(): Promise<{ sent_at: string }>;
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

  async getAdminOpsSummary(): Promise<AdminOpsSummary> {
    return this.httpClient.request<AdminOpsSummary>('/admin/ops/summary', {
      method: 'GET',
    });
  }

  async runAdminJob(jobKey: AdminJobKey, payload?: BackfillRunPayload): Promise<RunAdminJobResponse> {
    return this.httpClient.request<RunAdminJobResponse>(`/admin/ops/jobs/${jobKey}/run`, {
      method: 'POST',
      body: payload ? JSON.stringify(payload) : undefined,
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
}

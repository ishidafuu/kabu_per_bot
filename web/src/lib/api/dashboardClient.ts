import type { DashboardSummary } from '../../types/dashboard';
import { HttpClient } from './httpClient';

export interface DashboardClient {
  getSummary(): Promise<DashboardSummary>;
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
}

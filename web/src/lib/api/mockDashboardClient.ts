import type { DashboardSummary } from '../../types/dashboard';
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

export class MockDashboardClient implements DashboardClient {
  async getSummary(): Promise<DashboardSummary> {
    await wait(120);
    return {
      ...seedSummary,
      watchlist_count: getMockWatchlistCount(),
    };
  }
}

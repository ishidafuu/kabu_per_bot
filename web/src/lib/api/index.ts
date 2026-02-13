import { appConfig } from '../config';
import type { DashboardClient } from './dashboardClient';
import { HttpDashboardClient } from './dashboardClient';
import { HttpClient } from './httpClient';
import type { NotificationLogClient } from './notificationLogClient';
import { HttpNotificationLogClient } from './notificationLogClient';
import { MockDashboardClient } from './mockDashboardClient';
import { MockNotificationLogClient } from './mockNotificationLogClient';
import { MockWatchlistClient } from './mockWatchlistClient';
import { MockWatchlistHistoryClient } from './mockWatchlistHistoryClient';
import type { WatchlistClient } from './watchlistClient';
import { HttpWatchlistClient } from './watchlistClient';
import type { WatchlistHistoryClient } from './watchlistHistoryClient';
import { HttpWatchlistHistoryClient } from './watchlistHistoryClient';

interface ClientFactoryOptions {
  getToken: () => Promise<string | null>;
}

export const createWatchlistClient = (
  options: ClientFactoryOptions,
): WatchlistClient => {
  if (appConfig.useMockApi) {
    return new MockWatchlistClient();
  }

  const httpClient = new HttpClient(appConfig.apiBaseUrl, options.getToken);
  return new HttpWatchlistClient(httpClient);
};

export const createDashboardClient = (
  options: ClientFactoryOptions,
): DashboardClient => {
  if (appConfig.useMockApi) {
    return new MockDashboardClient();
  }

  const httpClient = new HttpClient(appConfig.apiBaseUrl, options.getToken);
  return new HttpDashboardClient(httpClient);
};

export const createWatchlistHistoryClient = (
  options: ClientFactoryOptions,
): WatchlistHistoryClient => {
  if (appConfig.useMockApi) {
    return new MockWatchlistHistoryClient();
  }

  const httpClient = new HttpClient(appConfig.apiBaseUrl, options.getToken);
  return new HttpWatchlistHistoryClient(httpClient);
};

export const createNotificationLogClient = (
  options: ClientFactoryOptions,
): NotificationLogClient => {
  if (appConfig.useMockApi) {
    return new MockNotificationLogClient();
  }

  const httpClient = new HttpClient(appConfig.apiBaseUrl, options.getToken);
  return new HttpNotificationLogClient(httpClient);
};

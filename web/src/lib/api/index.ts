import { appConfig } from '../config';
import { HttpClient } from './httpClient';
import { HttpNotificationLogClient } from './notificationLogClient';
import { MockNotificationLogClient } from './mockNotificationLogClient';
import { MockWatchlistClient } from './mockWatchlistClient';
import { MockWatchlistHistoryClient } from './mockWatchlistHistoryClient';
import { HttpWatchlistClient } from './watchlistClient';
import { HttpWatchlistHistoryClient } from './watchlistHistoryClient';
import type { NotificationLogClient } from './notificationLogClient';
import type { WatchlistClient } from './watchlistClient';
import type { WatchlistHistoryClient } from './watchlistHistoryClient';

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

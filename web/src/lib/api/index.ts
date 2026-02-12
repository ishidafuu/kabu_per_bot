import { appConfig } from '../config';
import { HttpClient } from './httpClient';
import { MockWatchlistClient } from './mockWatchlistClient';
import { HttpWatchlistClient } from './watchlistClient';
import type { WatchlistClient } from './watchlistClient';

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

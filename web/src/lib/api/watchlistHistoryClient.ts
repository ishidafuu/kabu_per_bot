import type { WatchlistHistoryListResponse } from '../../types/watchlistHistory';
import { HttpClient } from './httpClient';

export interface ListWatchlistHistoryParams {
  ticker?: string;
  limit?: number;
  offset?: number;
}

export interface WatchlistHistoryClient {
  list(params?: ListWatchlistHistoryParams): Promise<WatchlistHistoryListResponse>;
  updateReason(recordId: string, reason: string): Promise<void>;
}

export class HttpWatchlistHistoryClient implements WatchlistHistoryClient {
  private readonly httpClient: HttpClient;

  constructor(httpClient: HttpClient) {
    this.httpClient = httpClient;
  }

  async list(params: ListWatchlistHistoryParams = {}): Promise<WatchlistHistoryListResponse> {
    const query = new URLSearchParams();

    if (params.ticker) {
      query.set('ticker', params.ticker);
    }

    if (params.limit != null) {
      query.set('limit', String(params.limit));
    }

    if (params.offset != null) {
      query.set('offset', String(params.offset));
    }

    const suffix = query.toString();
    const path = suffix.length > 0 ? `/watchlist/history?${suffix}` : '/watchlist/history';

    return this.httpClient.request<WatchlistHistoryListResponse>(path, {
      method: 'GET',
    });
  }

  async updateReason(recordId: string, reason: string): Promise<void> {
    await this.httpClient.request(`/watchlist/history/${encodeURIComponent(recordId)}`, {
      method: 'PATCH',
      body: JSON.stringify({
        reason: reason.trim().length > 0 ? reason.trim() : null,
      }),
    });
  }
}

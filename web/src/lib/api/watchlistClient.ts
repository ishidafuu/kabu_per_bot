import type {
  WatchlistCreateInput,
  WatchlistItem,
  WatchlistListResponse,
  WatchlistUpdateInput,
} from '../../types/watchlist';
import { HttpClient } from './httpClient';

export interface ListWatchlistParams {
  q?: string;
  limit?: number;
  offset?: number;
}

export interface WatchlistClient {
  list(params?: ListWatchlistParams): Promise<WatchlistListResponse>;
  create(input: WatchlistCreateInput): Promise<WatchlistItem>;
  update(ticker: string, input: WatchlistUpdateInput): Promise<WatchlistItem>;
  remove(ticker: string): Promise<void>;
}

export class HttpWatchlistClient implements WatchlistClient {
  private readonly httpClient: HttpClient;

  constructor(httpClient: HttpClient) {
    this.httpClient = httpClient;
  }

  async list(params: ListWatchlistParams = {}): Promise<WatchlistListResponse> {
    const query = new URLSearchParams();

    if (params.q) {
      query.set('q', params.q);
    }

    if (params.limit != null) {
      query.set('limit', String(params.limit));
    }

    if (params.offset != null) {
      query.set('offset', String(params.offset));
    }

    const suffix = query.toString();
    const path = suffix.length > 0 ? `/watchlist?${suffix}` : '/watchlist';

    return this.httpClient.request<WatchlistListResponse>(path, {
      method: 'GET',
    });
  }

  async create(input: WatchlistCreateInput): Promise<WatchlistItem> {
    return this.httpClient.request<WatchlistItem>('/watchlist', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  }

  async update(ticker: string, input: WatchlistUpdateInput): Promise<WatchlistItem> {
    return this.httpClient.request<WatchlistItem>(`/watchlist/${encodeURIComponent(ticker)}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  }

  async remove(ticker: string): Promise<void> {
    await this.httpClient.request<void>(`/watchlist/${encodeURIComponent(ticker)}`, {
      method: 'DELETE',
    });
  }
}

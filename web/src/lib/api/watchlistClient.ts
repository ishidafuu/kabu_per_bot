import type {
  IrUrlCandidateListResponse,
  IrUrlCandidateSuggestInput,
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
  include_status?: boolean;
}

export interface WatchlistClient {
  list(params?: ListWatchlistParams): Promise<WatchlistListResponse>;
  suggestIrUrlCandidates(input: IrUrlCandidateSuggestInput): Promise<IrUrlCandidateListResponse>;
  create(input: WatchlistCreateInput): Promise<WatchlistItem>;
  update(ticker: string, input: WatchlistUpdateInput): Promise<WatchlistItem>;
  remove(ticker: string, reason?: string): Promise<void>;
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
    if (params.include_status != null) {
      query.set('include_status', String(params.include_status));
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

  async suggestIrUrlCandidates(input: IrUrlCandidateSuggestInput): Promise<IrUrlCandidateListResponse> {
    return this.httpClient.request<IrUrlCandidateListResponse>('/watchlist/ir-url-candidates', {
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

  async remove(ticker: string, reason?: string): Promise<void> {
    const query = new URLSearchParams();
    if (reason && reason.trim().length > 0) {
      query.set('reason', reason.trim());
    }
    const suffix = query.toString();
    const path = suffix.length > 0
      ? `/watchlist/${encodeURIComponent(ticker)}?${suffix}`
      : `/watchlist/${encodeURIComponent(ticker)}`;
    await this.httpClient.request<void>(path, {
      method: 'DELETE',
    });
  }
}

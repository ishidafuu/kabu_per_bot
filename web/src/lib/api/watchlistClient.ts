import type {
  IrUrlCandidateListResponse,
  IrUrlCandidateSuggestInput,
  WatchlistCreateInput,
  WatchlistItem,
  WatchlistListResponse,
  WatchlistUpdateInput,
} from '../../types/watchlist';
import type { WatchlistDetailResponse } from '../../types/watchlistDetail';
import { HttpClient } from './httpClient';

export interface GetWatchlistDetailParams {
  category?: string;
  strong_only?: boolean;
  sent_at_from?: string;
  sent_at_to?: string;
  limit?: number;
  offset?: number;
  history_limit?: number;
  history_offset?: number;
}

export interface ListWatchlistParams {
  q?: string;
  limit?: number;
  offset?: number;
  include_status?: boolean;
}

export interface WatchlistClient {
  list(params?: ListWatchlistParams): Promise<WatchlistListResponse>;
  getDetail(ticker: string, params?: GetWatchlistDetailParams): Promise<WatchlistDetailResponse>;
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

  async getDetail(ticker: string, params: GetWatchlistDetailParams = {}): Promise<WatchlistDetailResponse> {
    const query = new URLSearchParams();
    if (params.category) {
      query.set('category', params.category);
    }
    if (params.strong_only != null) {
      query.set('strong_only', String(params.strong_only));
    }
    if (params.sent_at_from) {
      query.set('sent_at_from', params.sent_at_from);
    }
    if (params.sent_at_to) {
      query.set('sent_at_to', params.sent_at_to);
    }
    if (params.limit != null) {
      query.set('limit', String(params.limit));
    }
    if (params.offset != null) {
      query.set('offset', String(params.offset));
    }
    if (params.history_limit != null) {
      query.set('history_limit', String(params.history_limit));
    }
    if (params.history_offset != null) {
      query.set('history_offset', String(params.history_offset));
    }
    const suffix = query.toString();
    const path = suffix.length > 0
      ? `/watchlist/${encodeURIComponent(ticker)}/detail?${suffix}`
      : `/watchlist/${encodeURIComponent(ticker)}/detail`;

    return this.httpClient.request<WatchlistDetailResponse>(path, {
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

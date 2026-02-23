import type { NotificationLogListResponse } from '../../types/notificationLog';
import type { WatchPriority } from '../../types/watchlist';
import { HttpClient } from './httpClient';

export interface ListNotificationLogParams {
  ticker?: string;
  priority?: WatchPriority;
  limit?: number;
  offset?: number;
}

export interface NotificationLogClient {
  list(params?: ListNotificationLogParams): Promise<NotificationLogListResponse>;
}

export class HttpNotificationLogClient implements NotificationLogClient {
  private readonly httpClient: HttpClient;

  constructor(httpClient: HttpClient) {
    this.httpClient = httpClient;
  }

  async list(params: ListNotificationLogParams = {}): Promise<NotificationLogListResponse> {
    const query = new URLSearchParams();

    if (params.ticker) {
      query.set('ticker', params.ticker);
    }
    if (params.priority) {
      query.set('priority', params.priority);
    }

    if (params.limit != null) {
      query.set('limit', String(params.limit));
    }

    if (params.offset != null) {
      query.set('offset', String(params.offset));
    }

    const suffix = query.toString();
    const path = suffix.length > 0 ? `/notifications/logs?${suffix}` : '/notifications/logs';

    return this.httpClient.request<NotificationLogListResponse>(path, {
      method: 'GET',
    });
  }
}

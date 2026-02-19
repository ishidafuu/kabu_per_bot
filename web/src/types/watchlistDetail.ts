import type { NotificationLogListResponse } from './notificationLog';
import type { WatchlistHistoryListResponse } from './watchlistHistory';
import type { WatchlistItem } from './watchlist';

export interface WatchlistDetailSummary {
  last_notification_at?: string | null;
  last_notification_category?: string | null;
  notification_count_7d: number;
  strong_notification_count_30d: number;
  data_unknown_count_30d: number;
}

export interface WatchlistDetailResponse {
  item: WatchlistItem;
  summary: WatchlistDetailSummary;
  notifications: NotificationLogListResponse;
  history: WatchlistHistoryListResponse;
}

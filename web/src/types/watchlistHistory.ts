export interface WatchlistHistoryItem {
  record_id: string;
  ticker: string;
  action: string;
  reason: string | null;
  acted_at: string;
}

export interface WatchlistHistoryListResponse {
  items: WatchlistHistoryItem[];
  total: number;
}

export interface NotificationLogItem {
  entry_id: string;
  ticker: string;
  category: string;
  condition_key: string;
  sent_at: string;
  channel: string;
  payload_hash: string;
  is_strong: boolean;
  body?: string | null;
  data_source?: string | null;
  data_fetched_at?: string | null;
}

export interface NotificationLogListResponse {
  items: NotificationLogItem[];
  total: number;
}

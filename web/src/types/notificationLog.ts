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
  evaluation_confidence?: number | null;
  evaluation_strength?: number | null;
  evaluation_lens_strengths?: Record<string, number> | null;
  evaluation_lens_confidences?: Record<string, number> | null;
}

export interface NotificationLogListResponse {
  items: NotificationLogItem[];
  total: number;
}

export interface CommitteeLogSummary {
  total: number;
  lens_hit_counts: Record<string, number>;
  confidence_distribution: Record<string, number>;
  strength_distribution: Record<string, number>;
}

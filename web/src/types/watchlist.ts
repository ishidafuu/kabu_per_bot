export type MetricType = 'PER' | 'PSR';

export type NotifyChannel = 'DISCORD' | 'OFF';

export type NotifyTiming = 'IMMEDIATE' | 'AT_21' | 'OFF';

export interface WatchlistItem {
  ticker: string;
  name: string;
  metric_type: MetricType;
  notify_channel: NotifyChannel;
  notify_timing: NotifyTiming;
  is_active: boolean;
  ai_enabled: boolean;
}

export interface WatchlistListResponse {
  items: WatchlistItem[];
  total: number;
}

export interface WatchlistCreateInput {
  ticker: string;
  name: string;
  metric_type: MetricType;
  notify_channel: NotifyChannel;
  notify_timing: NotifyTiming;
  is_active?: boolean;
  ai_enabled?: boolean;
}

export interface WatchlistUpdateInput {
  name?: string;
  metric_type?: MetricType;
  notify_channel?: NotifyChannel;
  notify_timing?: NotifyTiming;
  is_active?: boolean;
  ai_enabled?: boolean;
}

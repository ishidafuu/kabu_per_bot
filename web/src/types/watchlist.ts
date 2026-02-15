export type MetricType = 'PER' | 'PSR';

export type NotifyChannel = 'DISCORD' | 'OFF';

export type NotifyTiming = 'IMMEDIATE' | 'AT_21' | 'OFF';

export interface XAccountLink {
  handle: string;
  role?: string | null;
}

export interface WatchlistItem {
  ticker: string;
  name: string;
  metric_type: MetricType;
  notify_channel: NotifyChannel;
  notify_timing: NotifyTiming;
  is_active: boolean;
  ai_enabled: boolean;
  ir_urls: string[];
  x_official_account?: string | null;
  x_executive_accounts: XAccountLink[];
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
  reason?: string;
  ir_urls?: string[];
  x_official_account?: string;
  x_executive_accounts?: XAccountLink[];
  is_active?: boolean;
  ai_enabled?: boolean;
}

export interface WatchlistUpdateInput {
  name?: string;
  metric_type?: MetricType;
  notify_channel?: NotifyChannel;
  notify_timing?: NotifyTiming;
  ir_urls?: string[];
  x_official_account?: string;
  x_executive_accounts?: XAccountLink[];
  is_active?: boolean;
  ai_enabled?: boolean;
}

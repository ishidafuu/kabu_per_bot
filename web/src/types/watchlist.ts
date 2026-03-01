export type MetricType = 'PER' | 'PSR';

export type NotifyChannel = 'DISCORD' | 'OFF';

export type NotifyTiming = 'IMMEDIATE' | 'AT_21' | 'OFF';
export type WatchPriority = 'HIGH' | 'MEDIUM' | 'LOW';
export type EvaluationNotifyMode = 'ALL' | 'TOP_N' | 'ALERT_ONLY';

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
  priority: WatchPriority;
  always_notify_enabled?: boolean;
  is_active: boolean;
  ai_enabled: boolean;
  evaluation_enabled?: boolean;
  evaluation_notify_mode?: EvaluationNotifyMode;
  evaluation_top_n?: number;
  evaluation_min_strength?: number;
  ir_urls: string[];
  x_official_account?: string | null;
  x_executive_accounts: XAccountLink[];
  current_metric_value?: number | null;
  median_1w?: number | null;
  median_3m?: number | null;
  median_1y?: number | null;
  signal_category?: string | null;
  signal_combo?: string | null;
  signal_is_strong?: boolean | null;
  signal_streak_days?: number | null;
  notification_skip_reason?: string | null;
  next_earnings_date?: string | null;
  next_earnings_time?: string | null;
  next_earnings_days?: number | null;
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
  priority?: WatchPriority;
  always_notify_enabled?: boolean;
  evaluation_enabled?: boolean;
  evaluation_notify_mode?: EvaluationNotifyMode;
  evaluation_top_n?: number;
  evaluation_min_strength?: number;
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
  priority?: WatchPriority;
  always_notify_enabled?: boolean;
  evaluation_enabled?: boolean;
  evaluation_notify_mode?: EvaluationNotifyMode;
  evaluation_top_n?: number;
  evaluation_min_strength?: number;
  ir_urls?: string[];
  x_official_account?: string;
  x_executive_accounts?: XAccountLink[];
  is_active?: boolean;
  ai_enabled?: boolean;
}

export interface IrUrlCandidate {
  url: string;
  title: string;
  reason: string;
  confidence: 'High' | 'Med' | 'Low';
  validation_status: 'VALID' | 'WARNING' | 'INVALID';
  score: number;
  http_status?: number | null;
  content_type?: string;
}

export interface IrUrlCandidateSuggestInput {
  ticker: string;
  company_name: string;
  max_candidates?: number;
}

export interface IrUrlCandidateListResponse {
  items: IrUrlCandidate[];
  total: number;
  source: string;
}

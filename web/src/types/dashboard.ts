export interface DashboardSummary {
  watchlist_count: number;
  today_notification_count: number;
  today_data_unknown_count: number;
  failed_job_exists: boolean;
}

export type AdminJobKey =
  | 'immediate_open'
  | 'immediate_close'
  | 'daily'
  | 'daily_at21'
  | 'technical_daily'
  | 'technical_full_refresh'
  | 'earnings_weekly'
  | 'earnings_tomorrow'
  | 'committee_baseline_refresh'
  | 'backfill';

export interface AdminOpsJob {
  key: AdminJobKey;
  label: string;
  job_name?: string | null;
  configured: boolean;
}

export interface AdminSkipReason {
  reason: string;
  count: number;
}

export interface AdminOpsExecution {
  job_key: AdminJobKey;
  job_label: string;
  job_name: string;
  execution_name: string;
  status: string;
  create_time?: string | null;
  start_time?: string | null;
  completion_time?: string | null;
  message?: string | null;
  log_uri?: string | null;
  skip_reasons: AdminSkipReason[];
  skip_reason_error?: string | null;
}

export interface AdminOpsSummary {
  jobs: AdminOpsJob[];
  recent_executions: AdminOpsExecution[];
  latest_skip_reasons: AdminOpsExecution[];
}

export interface AdminImmediateSchedule {
  enabled: boolean;
  timezone: 'Asia/Tokyo';
  open_window_start: string;
  open_window_end: string;
  open_window_interval_min: number;
  close_window_start: string;
  close_window_end: string;
  close_window_interval_min: number;
}

export interface AdminGlobalSettings {
  cooldown_hours: number;
  intel_notification_max_age_days: number;
  immediate_schedule: AdminImmediateSchedule;
  grok_sns: AdminGrokSnsSettings;
  committee_daily_scheduled_time: string;
  baseline_monthly_scheduled_time: string;
  grok_balance: AdminGrokBalance;
  source: 'env_default' | 'firestore';
  updated_at?: string | null;
  updated_by?: string | null;
}

export interface AdminGrokSnsSettings {
  enabled: boolean;
  scheduled_time: string;
  per_ticker_cooldown_hours: number;
  prompt_template: string;
}

export interface AdminGrokBalance {
  configured: boolean;
  available: boolean;
  amount?: number | null;
  currency?: string | null;
  fetched_at?: string | null;
  error?: string | null;
}

export interface AdminGlobalSettingsUpdatePayload {
  cooldown_hours?: number;
  intel_notification_max_age_days?: number;
  immediate_schedule?: {
    enabled: boolean;
    open_window_start: string;
    open_window_end: string;
    open_window_interval_min: number;
    close_window_start: string;
    close_window_end: string;
    close_window_interval_min: number;
  };
  grok_sns?: {
    enabled: boolean;
    scheduled_time: string;
    per_ticker_cooldown_hours: number;
    prompt_template: string;
  };
  committee_daily_scheduled_time?: string;
  baseline_monthly_scheduled_time?: string;
}

export interface BackfillRunPayload {
  from_date: string;
  to_date: string;
  tickers: string[];
  dry_run: boolean;
}

export interface RunAdminJobResponse {
  execution: AdminOpsExecution;
}

export interface AdminGrokCooldownResetResponse {
  reset_at: string;
  deleted_entries: number;
  deleted_notification_logs: number;
  deleted_seen_entries: number;
  ticker?: string | null;
}

export interface DashboardSummary {
  watchlist_count: number;
  today_notification_count: number;
  today_data_unknown_count: number;
  failed_job_exists: boolean;
}

export type AdminJobKey =
  | 'daily'
  | 'daily_at21'
  | 'earnings_weekly'
  | 'earnings_tomorrow'
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

export interface AdminGlobalSettings {
  cooldown_hours: number;
  source: 'env_default' | 'firestore';
  updated_at?: string | null;
  updated_by?: string | null;
}

export interface AdminGlobalSettingsUpdatePayload {
  cooldown_hours: number;
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

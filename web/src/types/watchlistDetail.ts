import type { NotificationLogListResponse } from './notificationLog';
import type { WatchlistHistoryListResponse } from './watchlistHistory';
import type { WatchlistItem } from './watchlist';

export type TechnicalAlertOperator = 'IS_TRUE' | 'IS_FALSE' | 'GTE' | 'LTE' | 'BETWEEN' | 'OUTSIDE';

export interface TechnicalAlertRule {
  rule_id: string;
  ticker: string;
  rule_name: string;
  field_key: string;
  operator: TechnicalAlertOperator;
  threshold_value?: number | null;
  threshold_upper?: number | null;
  is_active: boolean;
  note?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TechnicalAlertRuleListResponse {
  items: TechnicalAlertRule[];
  total: number;
}

export interface TechnicalAlertRuleCreateInput {
  rule_name: string;
  field_key: string;
  operator: TechnicalAlertOperator;
  threshold_value?: number | null;
  threshold_upper?: number | null;
  is_active?: boolean;
  note?: string | null;
}

export interface TechnicalAlertRuleUpdateInput {
  rule_name?: string;
  field_key?: string;
  operator?: TechnicalAlertOperator;
  threshold_value?: number | null;
  threshold_upper?: number | null;
  is_active?: boolean | null;
  note?: string | null;
}

export interface TechnicalIndicatorSnapshot {
  ticker: string;
  trade_date: string;
  schema_version: number;
  calculated_at: string;
  values: Record<string, string | number | boolean | null>;
}

export interface TechnicalInitialFetchResponse {
  execution_name: string;
  status: string;
  job_key: string;
  job_label: string;
  message?: string | null;
}

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
  technical_rules: TechnicalAlertRuleListResponse;
  latest_technical?: TechnicalIndicatorSnapshot | null;
  technical_alert_history: NotificationLogListResponse;
}

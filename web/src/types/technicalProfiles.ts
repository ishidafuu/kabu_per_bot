export type TechnicalProfileType = 'SYSTEM' | 'CUSTOM';

export interface TechnicalProfile {
  profile_id: string;
  profile_type: TechnicalProfileType;
  profile_key: string;
  name: string;
  description: string;
  base_profile_key?: string | null;
  priority_order?: number | null;
  manual_assign_recommended: boolean;
  auto_assign: Record<string, unknown>;
  thresholds: Record<string, number>;
  weights: Record<string, number>;
  flags: Record<string, boolean>;
  strong_alerts: string[];
  weak_alerts: string[];
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TechnicalProfileListResponse {
  items: TechnicalProfile[];
  total: number;
}

export interface TechnicalProfileCreateInput {
  profile_key: string;
  name: string;
  description: string;
  base_profile_key?: string | null;
  priority_order?: number | null;
  manual_assign_recommended?: boolean;
  auto_assign?: Record<string, unknown>;
  thresholds?: Record<string, number>;
  weights?: Record<string, number>;
  flags?: Record<string, boolean>;
  strong_alerts?: string[];
  weak_alerts?: string[];
  is_active?: boolean;
}

export interface TechnicalProfileUpdateInput {
  name?: string;
  description?: string;
  priority_order?: number | null;
  manual_assign_recommended?: boolean;
  auto_assign?: Record<string, unknown>;
  thresholds?: Record<string, number>;
  weights?: Record<string, number>;
  flags?: Record<string, boolean>;
  strong_alerts?: string[];
  weak_alerts?: string[];
  is_active?: boolean;
}

export interface TechnicalProfileCloneInput {
  profile_key: string;
  name: string;
  description?: string | null;
}

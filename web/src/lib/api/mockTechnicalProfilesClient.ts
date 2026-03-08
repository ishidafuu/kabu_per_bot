import type {
  TechnicalProfile,
  TechnicalProfileCloneInput,
  TechnicalProfileCreateInput,
  TechnicalProfileListResponse,
  TechnicalProfileUpdateInput,
} from '../../types/technicalProfiles';
import type { TechnicalProfilesClient } from './technicalProfilesClient';

const wait = (ms: number): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

const seedProfiles: TechnicalProfile[] = [
  {
    profile_id: 'system_low_liquidity',
    profile_type: 'SYSTEM',
    profile_key: 'low_liquidity',
    name: '低流動性',
    description: '低流動性銘柄向け。ノイズ通知を抑制します。',
    base_profile_key: null,
    priority_order: 1,
    manual_assign_recommended: false,
    auto_assign: { any: [{ avg_turnover_20d_lt: 100000000 }, { median_turnover_20d_lt: 70000000 }] },
    thresholds: { volume_spike: 3, turnover_spike: 3, overheated_short: 25 },
    weights: { trend: 25, demand: 20, heat: 15, long_term: 10, liquidity: 30 },
    flags: { use_ma200_weight: false, suppress_minor_alerts: true },
    strong_alerts: ['breakdown_ma75', 'sharp_drop_high_volume', 'trend_change_to_down'],
    weak_alerts: ['cross_up_ma25', 'cross_up_ma75'],
    is_active: true,
    created_at: '2026-03-08T00:00:00+09:00',
    updated_at: '2026-03-08T00:00:00+09:00',
  },
  {
    profile_id: 'system_large_core',
    profile_type: 'SYSTEM',
    profile_key: 'large_core',
    name: '大型・主力',
    description: '大型・主力株向け。200日線と52週高値からの距離を重視します。',
    base_profile_key: null,
    priority_order: 2,
    manual_assign_recommended: false,
    auto_assign: { all: [{ market_cap_gte: 500000000000 }, { avg_turnover_20d_gte: 2000000000 }] },
    thresholds: { volume_spike: 1.6, turnover_spike: 1.6, overheated_short: 10 },
    weights: { trend: 25, demand: 20, heat: 15, long_term: 40, liquidity: 0 },
    flags: { use_ma200_weight: true, suppress_minor_alerts: false },
    strong_alerts: ['cross_down_ma200', 'trend_change_to_down', 'sharp_drop_high_volume'],
    weak_alerts: ['cross_up_ma200', 'near_ytd_high_breakout', 'turnover_spike'],
    is_active: true,
    created_at: '2026-03-08T00:00:00+09:00',
    updated_at: '2026-03-08T00:00:00+09:00',
  },
  {
    profile_id: 'system_value_dividend',
    profile_type: 'SYSTEM',
    profile_key: 'value_dividend',
    name: '高配当・バリュー',
    description: '高配当・バリュー株向け。当面は手動割当推奨です。',
    base_profile_key: null,
    priority_order: 3,
    manual_assign_recommended: true,
    auto_assign: { manual_only: true },
    thresholds: { volume_spike: 1.5, turnover_spike: 1.5, overheated_short: 8 },
    weights: { trend: 20, demand: 15, heat: 10, long_term: 35, liquidity: 20 },
    flags: { use_ma200_weight: true, use_dividend_event: true, suppress_minor_alerts: false },
    strong_alerts: ['cross_down_ma200', 'trend_change_to_down', 'sharp_drop_high_volume'],
    weak_alerts: ['cross_up_ma200', 'near_ytd_high_breakout'],
    is_active: true,
    created_at: '2026-03-08T00:00:00+09:00',
    updated_at: '2026-03-08T00:00:00+09:00',
  },
  {
    profile_id: 'system_small_growth',
    profile_type: 'SYSTEM',
    profile_key: 'small_growth',
    name: '小型成長',
    description: '小型成長株向け。需給と25日線/75日線を重視します。',
    base_profile_key: null,
    priority_order: 4,
    manual_assign_recommended: false,
    auto_assign: { all: [{ market_cap_lt: 500000000000 }, { avg_turnover_20d_gte: 100000000 }] },
    thresholds: { volume_spike: 2, turnover_spike: 2, overheated_short: 18 },
    weights: { trend: 25, demand: 35, heat: 25, long_term: 10, liquidity: 5 },
    flags: { use_ma200_weight: false, suppress_minor_alerts: false },
    strong_alerts: ['cross_down_ma75', 'trend_change_to_down', 'sharp_drop_high_volume'],
    weak_alerts: ['near_ytd_high_breakout', 'rebound_from_ma25', 'rebound_after_pullback', 'turnover_spike'],
    is_active: true,
    created_at: '2026-03-08T00:00:00+09:00',
    updated_at: '2026-03-08T00:00:00+09:00',
  },
];

let profilesStore = [...seedProfiles];

const sortProfiles = (rows: TechnicalProfile[]): TechnicalProfile[] =>
  [...rows].sort((left, right) => {
    if (left.profile_type !== right.profile_type) {
      return left.profile_type === 'SYSTEM' ? -1 : 1;
    }
    return (left.priority_order ?? 9999) - (right.priority_order ?? 9999) || left.name.localeCompare(right.name, 'ja');
  });

export class MockTechnicalProfilesClient implements TechnicalProfilesClient {
  async list(): Promise<TechnicalProfileListResponse> {
    await wait(80);
    const items = sortProfiles(profilesStore);
    return { items, total: items.length };
  }

  async get(profileId: string): Promise<TechnicalProfile> {
    await wait(60);
    const found = profilesStore.find((row) => row.profile_id === profileId);
    if (!found) {
      throw new Error('profile not found');
    }
    return found;
  }

  async create(input: TechnicalProfileCreateInput): Promise<TechnicalProfile> {
    await wait(120);
    const profileKey = input.profile_key.trim().toLowerCase();
    if (profilesStore.some((row) => row.profile_key === profileKey)) {
      throw new Error('profile_key は既に使用されています。');
    }
    const now = new Date().toISOString();
    const created: TechnicalProfile = {
      profile_id: `custom_${profileKey}`,
      profile_type: 'CUSTOM',
      profile_key: profileKey,
      name: input.name,
      description: input.description,
      base_profile_key: input.base_profile_key ?? null,
      priority_order: input.priority_order ?? null,
      manual_assign_recommended: input.manual_assign_recommended ?? false,
      auto_assign: input.auto_assign ?? {},
      thresholds: input.thresholds ?? {},
      weights: input.weights ?? {},
      flags: input.flags ?? {},
      strong_alerts: input.strong_alerts ?? [],
      weak_alerts: input.weak_alerts ?? [],
      is_active: input.is_active ?? true,
      created_at: now,
      updated_at: now,
    };
    profilesStore = sortProfiles([...profilesStore, created]);
    return created;
  }

  async clone(profileId: string, input: TechnicalProfileCloneInput): Promise<TechnicalProfile> {
    await wait(120);
    const source = profilesStore.find((row) => row.profile_id === profileId);
    if (!source) {
      throw new Error('profile not found');
    }
    return this.create({
      profile_key: input.profile_key,
      name: input.name,
      description: input.description ?? source.description,
      base_profile_key: source.profile_key,
      priority_order: source.priority_order,
      manual_assign_recommended: source.manual_assign_recommended,
      auto_assign: source.auto_assign,
      thresholds: source.thresholds,
      weights: source.weights,
      flags: source.flags,
      strong_alerts: source.strong_alerts,
      weak_alerts: source.weak_alerts,
      is_active: source.is_active,
    });
  }

  async update(profileId: string, input: TechnicalProfileUpdateInput): Promise<TechnicalProfile> {
    await wait(120);
    const index = profilesStore.findIndex((row) => row.profile_id === profileId);
    if (index < 0) {
      throw new Error('profile not found');
    }
    const current = profilesStore[index];
    if (current.profile_type === 'SYSTEM') {
      throw new Error('SYSTEM profile は編集できません。');
    }
    const updated: TechnicalProfile = {
      ...current,
      name: input.name ?? current.name,
      description: input.description ?? current.description,
      priority_order: input.priority_order ?? current.priority_order ?? null,
      manual_assign_recommended: input.manual_assign_recommended ?? current.manual_assign_recommended,
      auto_assign: input.auto_assign ?? current.auto_assign,
      thresholds: input.thresholds ?? current.thresholds,
      weights: input.weights ?? current.weights,
      flags: input.flags ?? current.flags,
      strong_alerts: input.strong_alerts ?? current.strong_alerts,
      weak_alerts: input.weak_alerts ?? current.weak_alerts,
      is_active: input.is_active ?? current.is_active,
      updated_at: new Date().toISOString(),
    };
    profilesStore = sortProfiles(profilesStore.map((row, rowIndex) => (rowIndex === index ? updated : row)));
    return updated;
  }
}

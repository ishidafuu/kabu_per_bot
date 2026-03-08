import type { TechnicalAlertOperator } from '../types/watchlistDetail';

export type TechnicalFieldValueType = 'number' | 'boolean';

export interface TechnicalFieldOption {
  key: string;
  label: string;
  categoryKey: string;
  categoryLabel: string;
  valueType: TechnicalFieldValueType;
}

export interface TechnicalRuleTemplate {
  id: string;
  label: string;
  description: string;
  ruleName: string;
  fieldKey: string;
  operator: TechnicalAlertOperator;
  thresholdValue?: number;
  thresholdUpper?: number;
  note: string;
}

const PROFILE_TEMPLATE_IDS = {
  low_liquidity: ['sharp-drop-high-volume', 'cross-up-ma75', 'turnover-spike'],
  large_core: ['cross-up-ma200', 'near-ytd-high-breakout', 'turnover-spike'],
  value_dividend: ['cross-up-ma200', 'near-ytd-high-breakout'],
  small_growth: ['rebound-ma25', 'near-ytd-high-breakout', 'turnover-spike'],
} as const;

const CATEGORY_LABELS = {
  price: '価格系',
  trend: 'トレンド系',
  highLow: '高値安値系',
  supplyDemand: '需給系',
  candle: '日足強弱系',
  returns: '変化率系',
  volatility: 'ボラティリティ系',
  signal: '判定フラグ系',
  event: 'イベント系',
  extended: '拡張項目',
} as const;

const buildFieldOption = (
  categoryKey: keyof typeof CATEGORY_LABELS,
  key: string,
  label: string,
  valueType: TechnicalFieldValueType,
): TechnicalFieldOption => ({
  key,
  label,
  categoryKey,
  categoryLabel: CATEGORY_LABELS[categoryKey],
  valueType,
});

export const TECHNICAL_FIELD_OPTIONS: readonly TechnicalFieldOption[] = [
  buildFieldOption('price', 'close', '終値', 'number'),
  buildFieldOption('price', 'open', '始値', 'number'),
  buildFieldOption('price', 'high', '高値', 'number'),
  buildFieldOption('price', 'low', '安値', 'number'),
  buildFieldOption('price', 'prev_close', '前日終値', 'number'),
  buildFieldOption('price', 'change', '前日比', 'number'),
  buildFieldOption('price', 'change_pct', '前日比率', 'number'),
  buildFieldOption('price', 'intraday_range', '日中値幅', 'number'),
  buildFieldOption('price', 'intraday_range_pct', '日中値幅率', 'number'),

  buildFieldOption('trend', 'ma_5', '5日移動平均線', 'number'),
  buildFieldOption('trend', 'ma_25', '25日移動平均線', 'number'),
  buildFieldOption('trend', 'ma_75', '75日移動平均線', 'number'),
  buildFieldOption('trend', 'ma_200', '200日移動平均線', 'number'),
  buildFieldOption('trend', 'dev_5', '5日線乖離率', 'number'),
  buildFieldOption('trend', 'dev_25', '25日線乖離率', 'number'),
  buildFieldOption('trend', 'dev_75', '75日線乖離率', 'number'),
  buildFieldOption('trend', 'dev_200', '200日線乖離率', 'number'),
  buildFieldOption('trend', 'close_vs_ma5', '5日線との位置関係', 'number'),
  buildFieldOption('trend', 'close_vs_ma25', '25日線との位置関係', 'number'),
  buildFieldOption('trend', 'close_vs_ma75', '75日線との位置関係', 'number'),
  buildFieldOption('trend', 'close_vs_ma200', '200日線との位置関係', 'number'),
  buildFieldOption('trend', 'slope_ma25', '25日線の傾き', 'number'),
  buildFieldOption('trend', 'slope_ma75', '75日線の傾き', 'number'),
  buildFieldOption('trend', 'slope_ma200', '200日線の傾き', 'number'),
  buildFieldOption('trend', 'perfect_order_flag', 'パーフェクトオーダー判定', 'boolean'),

  buildFieldOption('highLow', 'ytd_high', '年初来高値', 'number'),
  buildFieldOption('highLow', 'ytd_low', '年初来安値', 'number'),
  buildFieldOption('highLow', 'drawdown_from_ytd_high', '年初来高値からの下落率', 'number'),
  buildFieldOption('highLow', 'rebound_from_ytd_low', '年初来安値からの上昇率', 'number'),
  buildFieldOption('highLow', 'high_20d', '20日高値', 'number'),
  buildFieldOption('highLow', 'low_20d', '20日安値', 'number'),
  buildFieldOption('highLow', 'high_52w', '52週高値', 'number'),
  buildFieldOption('highLow', 'low_52w', '52週安値', 'number'),
  buildFieldOption('highLow', 'drawdown_from_52w_high', '52週高値からの下落率', 'number'),
  buildFieldOption('highLow', 'new_high_20d', '20日高値更新フラグ', 'boolean'),
  buildFieldOption('highLow', 'new_high_52w', '52週高値更新フラグ', 'boolean'),
  buildFieldOption('highLow', 'new_low_20d', '20日安値更新フラグ', 'boolean'),
  buildFieldOption('highLow', 'new_low_52w', '52週安値更新フラグ', 'boolean'),
  buildFieldOption('highLow', 'days_from_20d_high', '20日高値からの経過日数', 'number'),
  buildFieldOption('highLow', 'days_from_ytd_high', '年初来高値からの経過日数', 'number'),
  buildFieldOption('highLow', 'days_from_52w_high', '52週高値からの経過日数', 'number'),

  buildFieldOption('supplyDemand', 'volume', '出来高', 'number'),
  buildFieldOption('supplyDemand', 'turnover_value', '売買代金', 'number'),
  buildFieldOption('supplyDemand', 'avg_volume_20d', '20日平均出来高', 'number'),
  buildFieldOption('supplyDemand', 'avg_turnover_20d', '20日平均売買代金', 'number'),
  buildFieldOption('supplyDemand', 'median_volume_20d', '20日出来高中央値', 'number'),
  buildFieldOption('supplyDemand', 'median_turnover_20d', '20日売買代金中央値', 'number'),
  buildFieldOption('supplyDemand', 'volume_ratio', '出来高倍率', 'number'),
  buildFieldOption('supplyDemand', 'turnover_ratio', '売買代金倍率', 'number'),

  buildFieldOption('candle', 'close_position_in_range', '当日値幅内終値位置', 'number'),
  buildFieldOption('candle', 'upper_shadow_ratio', '上ヒゲ比率', 'number'),
  buildFieldOption('candle', 'lower_shadow_ratio', '下ヒゲ比率', 'number'),
  buildFieldOption('candle', 'gap_up_down_pct', 'ギャップ率', 'number'),
  buildFieldOption('candle', 'true_range', 'トゥルーレンジ', 'number'),

  buildFieldOption('returns', 'return_3d', '3営業日騰落率', 'number'),
  buildFieldOption('returns', 'return_5d', '5営業日騰落率', 'number'),
  buildFieldOption('returns', 'return_10d', '10営業日騰落率', 'number'),
  buildFieldOption('returns', 'return_20d', '20営業日騰落率', 'number'),
  buildFieldOption('returns', 'return_60d', '60営業日騰落率', 'number'),

  buildFieldOption('volatility', 'atr_14', '14日ATR', 'number'),
  buildFieldOption('volatility', 'atr_pct_14', '14日ATR率', 'number'),
  buildFieldOption('volatility', 'volatility_20d', '20日ボラティリティ', 'number'),

  buildFieldOption('signal', 'trend_short_up', '短期上昇トレンド', 'boolean'),
  buildFieldOption('signal', 'trend_mid_up', '中期上昇トレンド', 'boolean'),
  buildFieldOption('signal', 'trend_long_up', '長期上昇トレンド', 'boolean'),
  buildFieldOption('signal', 'above_ma5', '5日線上フラグ', 'boolean'),
  buildFieldOption('signal', 'above_ma25', '25日線上フラグ', 'boolean'),
  buildFieldOption('signal', 'above_ma75', '75日線上フラグ', 'boolean'),
  buildFieldOption('signal', 'above_ma200', '200日線上フラグ', 'boolean'),
  buildFieldOption('signal', 'ytd_high_near', '年初来高値接近フラグ', 'boolean'),
  buildFieldOption('signal', 'overheated_short', '短期過熱フラグ', 'boolean'),
  buildFieldOption('signal', 'overheated_mid', '中期過熱フラグ', 'boolean'),
  buildFieldOption('signal', 'liquidity_ok', '流動性基準クリア', 'boolean'),
  buildFieldOption('signal', 'volume_expanding', '出来高拡大フラグ', 'boolean'),
  buildFieldOption('signal', 'turnover_expanding', '売買代金拡大フラグ', 'boolean'),
  buildFieldOption('signal', 'breakdown_ma75', '75日線割れフラグ', 'boolean'),
  buildFieldOption('signal', 'rebound_from_ma25', '25日線反発フラグ', 'boolean'),
  buildFieldOption('signal', 'rebound_from_ma75', '75日線反発フラグ', 'boolean'),

  buildFieldOption('event', 'cross_up_ma25', '25日線上抜け', 'boolean'),
  buildFieldOption('event', 'cross_down_ma25', '25日線下抜け', 'boolean'),
  buildFieldOption('event', 'cross_up_ma75', '75日線上抜け', 'boolean'),
  buildFieldOption('event', 'cross_down_ma75', '75日線下抜け', 'boolean'),
  buildFieldOption('event', 'new_ytd_high', '年初来高値更新', 'boolean'),
  buildFieldOption('event', 'near_ytd_high_breakout', '年初来高値ブレイク接近', 'boolean'),
  buildFieldOption('event', 'turnover_spike', '売買代金急増', 'boolean'),
  buildFieldOption('event', 'volume_spike', '出来高急増', 'boolean'),
  buildFieldOption('event', 'sharp_drop_high_volume', '大商い下落', 'boolean'),
  buildFieldOption('event', 'rebound_after_pullback', '押し目後反発', 'boolean'),
  buildFieldOption('event', 'trend_change_to_up', '上昇トレンド転換', 'boolean'),
  buildFieldOption('event', 'trend_change_to_down', '下落トレンド転換', 'boolean'),

  buildFieldOption('extended', 'body_ratio', '実体比率', 'number'),
  buildFieldOption('extended', 'high_52w_near', '52週高値接近フラグ', 'boolean'),
  buildFieldOption('extended', 'cross_up_ma5', '5日線上抜け', 'boolean'),
  buildFieldOption('extended', 'cross_down_ma5', '5日線下抜け', 'boolean'),
  buildFieldOption('extended', 'cross_up_ma200', '200日線上抜け', 'boolean'),
  buildFieldOption('extended', 'cross_down_ma200', '200日線下抜け', 'boolean'),
  buildFieldOption('extended', 'median_turnover_60d', '60日売買代金中央値', 'number'),
  buildFieldOption('extended', 'turnover_stability_flag', '売買代金安定フラグ', 'boolean'),
] as const;

export const TECHNICAL_FIELD_OPTION_MAP = new Map(TECHNICAL_FIELD_OPTIONS.map((row) => [row.key, row]));
export const TECHNICAL_SUPPORTED_FIELD_KEYS = new Set(TECHNICAL_FIELD_OPTIONS.map((row) => row.key));

export const TECHNICAL_RULE_TEMPLATES: readonly TechnicalRuleTemplate[] = [
  {
    id: 'recover-ma25',
    label: '25日線回復',
    description: '終値が25日線を上回ったタイミングを拾います。',
    ruleName: '25日線回復',
    fieldKey: 'close_vs_ma25',
    operator: 'GTE',
    thresholdValue: 0,
    note: '終値ベースで25日線を回復した日に通知',
  },
  {
    id: 'cross-up-ma75',
    label: '75日線上抜け',
    description: '中期線を下から上に抜けた日を通知します。',
    ruleName: '75日線上抜け',
    fieldKey: 'cross_up_ma75',
    operator: 'IS_TRUE',
    note: '中期トレンド転換の初動監視向け',
  },
  {
    id: 'cross-up-ma200',
    label: '200日線上抜け',
    description: '長期線を下から上に抜けた日を通知します。',
    ruleName: '200日線上抜け',
    fieldKey: 'cross_up_ma200',
    operator: 'IS_TRUE',
    note: '大型株や高配当株の長期トレンド転換監視向け',
  },
  {
    id: 'new-high-20d',
    label: '20日高値更新',
    description: '短期ブレイクアウトを検知します。',
    ruleName: '20日高値更新',
    fieldKey: 'new_high_20d',
    operator: 'IS_TRUE',
    note: '短期高値ブレイク時に通知',
  },
  {
    id: 'new-high-52w',
    label: '52週高値更新',
    description: '長期の高値更新を検知します。',
    ruleName: '52週高値更新',
    fieldKey: 'new_high_52w',
    operator: 'IS_TRUE',
    note: '長期上昇の継続確認向け',
  },
  {
    id: 'volume-spike',
    label: '出来高急増',
    description: '出来高が平常時の2倍以上に膨らんだ日を拾います。',
    ruleName: '出来高急増',
    fieldKey: 'volume_ratio',
    operator: 'GTE',
    thresholdValue: 2,
    note: '出来高倍率が2倍以上の日に通知',
  },
  {
    id: 'turnover-spike',
    label: '売買代金急増',
    description: '売買代金の急増を検知します。',
    ruleName: '売買代金急増',
    fieldKey: 'turnover_ratio',
    operator: 'GTE',
    thresholdValue: 2,
    note: '売買代金倍率が2倍以上の日に通知',
  },
  {
    id: 'trend-mid-up',
    label: '中期上昇トレンド',
    description: '中期的な上昇トレンド入りを継続監視します。',
    ruleName: '中期上昇トレンド',
    fieldKey: 'trend_mid_up',
    operator: 'IS_TRUE',
    note: 'ma25 > ma75 かつ slope_ma75 > 0 の上昇トレンド判定',
  },
  {
    id: 'perfect-order',
    label: 'パーフェクトオーダー',
    description: '短中長期線が理想的な上昇並びになった時を通知します。',
    ruleName: 'パーフェクトオーダー',
    fieldKey: 'perfect_order_flag',
    operator: 'IS_TRUE',
    note: '強い上昇トレンドの確認向け',
  },
  {
    id: 'rebound-ma25',
    label: '25日線反発',
    description: '25日線接触後の反発を検知します。',
    ruleName: '25日線反発',
    fieldKey: 'rebound_from_ma25',
    operator: 'IS_TRUE',
    note: '押し目候補の監視向け',
  },
  {
    id: 'sharp-drop-high-volume',
    label: '大商い下落',
    description: '高出来高を伴う大きな下落を検知します。',
    ruleName: '大商い下落',
    fieldKey: 'sharp_drop_high_volume',
    operator: 'IS_TRUE',
    note: '需給悪化の警戒シグナル',
  },
  {
    id: 'near-ytd-high-breakout',
    label: '年初来高値接近ブレイク',
    description: '高値接近と売買代金増加を伴うブレイク前後を拾います。',
    ruleName: '年初来高値接近ブレイク',
    fieldKey: 'near_ytd_high_breakout',
    operator: 'IS_TRUE',
    note: '高値圏での出来高伴う上放れ監視向け',
  },
] as const;

export const getRecommendedTechnicalRuleTemplates = (profileKey?: string | null): TechnicalRuleTemplate[] => {
  if (!profileKey) {
    return [];
  }
  const ids = PROFILE_TEMPLATE_IDS[profileKey as keyof typeof PROFILE_TEMPLATE_IDS];
  if (!ids) {
    return [];
  }
  return ids
    .map((id) => TECHNICAL_RULE_TEMPLATES.find((row) => row.id === id))
    .filter((row): row is TechnicalRuleTemplate => row != null);
};

export const TECHNICAL_HIGHLIGHT_KEYS = [
  'close_vs_ma25',
  'close_vs_ma75',
  'close_vs_ma200',
  'volume_ratio',
  'turnover_ratio',
  'atr_pct_14',
  'volatility_20d',
  'cross_up_ma25',
  'new_high_20d',
] as const;

export const getTechnicalFieldOption = (fieldKey: string): TechnicalFieldOption | undefined => {
  return TECHNICAL_FIELD_OPTION_MAP.get(fieldKey);
};

export const isBooleanTechnicalField = (fieldKey: string): boolean => {
  return getTechnicalFieldOption(fieldKey)?.valueType === 'boolean';
};

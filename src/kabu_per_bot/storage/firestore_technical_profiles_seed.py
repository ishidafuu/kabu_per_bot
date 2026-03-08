from __future__ import annotations

from copy import deepcopy

from kabu_per_bot.storage.firestore_migration import DocumentStore
from kabu_per_bot.storage.firestore_schema import COLLECTION_TECHNICAL_PROFILES, technical_profile_doc_id


TECHNICAL_PROFILE_SEED_ID = "technical_profiles_system_defaults"
TECHNICAL_PROFILE_SEED_DOC_PATH = f"_meta/schema/seeds/{TECHNICAL_PROFILE_SEED_ID}"
TECHNICAL_PROFILE_KEYS = (
    "low_liquidity",
    "large_core",
    "value_dividend",
    "small_growth",
)

SYSTEM_TECHNICAL_PROFILES: tuple[dict[str, object], ...] = (
    {
        "profile_id": "system_low_liquidity",
        "profile_type": "SYSTEM",
        "profile_key": "low_liquidity",
        "base_profile_key": "low_liquidity",
        "name": "低流動性",
        "description": "低流動性。単日スパイクのノイズが多いため、通知を絞る",
        "priority_order": 1,
        "manual_assign_recommended": False,
        "auto_assign": {
            "any": [
                {"avg_turnover_20d_lt": 100000000},
                {"median_turnover_20d_lt": 70000000},
            ]
        },
        "thresholds": {
            "overheated_short": 25.0,
            "overheated_mid": 35.0,
            "liquidity_ok": 100000000,
            "volume_expanding": 2.5,
            "turnover_expanding": 2.5,
            "volume_spike": 3.0,
            "turnover_spike": 3.0,
            "ytd_high_near_ratio": 0.97,
            "near_ytd_high_breakout_ratio": 0.99,
            "near_ytd_high_breakout_turnover_ratio": 2.0,
            "sharp_drop_change_pct": -7.0,
            "sharp_drop_volume_ratio": 3.0,
            "sharp_drop_close_position_max": 0.30,
            "rebound_touch_band_pct": 2.0,
            "rebound_close_position_min": 0.65,
        },
        "weights": {"trend": 25, "demand": 20, "heat": 15, "long_term": 10, "liquidity": 30},
        "flags": {
            "use_ma200_weight": False,
            "use_dividend_event": False,
            "suppress_minor_alerts": True,
        },
        "strong_alerts": ["breakdown_ma75", "sharp_drop_high_volume", "trend_change_to_down"],
        "weak_alerts": ["cross_up_ma25", "cross_up_ma75"],
        "is_active": True,
    },
    {
        "profile_id": "system_large_core",
        "profile_type": "SYSTEM",
        "profile_key": "large_core",
        "base_profile_key": "large_core",
        "name": "大型・主力",
        "description": "大型・主力。200日線と52週高値からの距離を重視",
        "priority_order": 2,
        "manual_assign_recommended": False,
        "auto_assign": {
            "all": [
                {"market_cap_gte": 500000000000},
                {"avg_turnover_20d_gte": 2000000000},
            ]
        },
        "thresholds": {
            "overheated_short": 10.0,
            "overheated_mid": 18.0,
            "liquidity_ok": 2000000000,
            "volume_expanding": 1.3,
            "turnover_expanding": 1.3,
            "volume_spike": 1.6,
            "turnover_spike": 1.6,
            "ytd_high_near_ratio": 0.98,
            "near_ytd_high_breakout_ratio": 0.995,
            "near_ytd_high_breakout_turnover_ratio": 1.2,
            "sharp_drop_change_pct": -4.0,
            "sharp_drop_volume_ratio": 1.5,
            "sharp_drop_close_position_max": 0.35,
            "rebound_touch_band_pct": 1.5,
            "rebound_close_position_min": 0.55,
        },
        "weights": {"trend": 25, "demand": 20, "heat": 15, "long_term": 40, "liquidity": 0},
        "flags": {
            "use_ma200_weight": True,
            "use_dividend_event": False,
            "suppress_minor_alerts": False,
        },
        "strong_alerts": ["cross_down_ma200", "trend_change_to_down", "sharp_drop_high_volume"],
        "weak_alerts": ["cross_up_ma200", "near_ytd_high_breakout", "turnover_spike"],
        "is_active": True,
    },
    {
        "profile_id": "system_value_dividend",
        "profile_type": "SYSTEM",
        "profile_key": "value_dividend",
        "base_profile_key": "value_dividend",
        "name": "高配当・バリュー",
        "description": "高配当・バリュー。まずは手動割当推奨。配当イベント補正を将来反映",
        "priority_order": 3,
        "manual_assign_recommended": True,
        "auto_assign": {
            "manual_only": True,
            "fallback_rule": {
                "all": [
                    {"market_cap_gte": 100000000000},
                    {"avg_turnover_20d_gte": 300000000},
                    {"volatility_20d_lte": 25.0},
                ]
            },
        },
        "thresholds": {
            "overheated_short": 8.0,
            "overheated_mid": 15.0,
            "liquidity_ok": 300000000,
            "volume_expanding": 1.2,
            "turnover_expanding": 1.2,
            "volume_spike": 1.5,
            "turnover_spike": 1.5,
            "ytd_high_near_ratio": 0.98,
            "near_ytd_high_breakout_ratio": 0.995,
            "near_ytd_high_breakout_turnover_ratio": 1.1,
            "sharp_drop_change_pct": -3.5,
            "sharp_drop_volume_ratio": 1.3,
            "sharp_drop_close_position_max": 0.40,
            "rebound_touch_band_pct": 1.5,
            "rebound_close_position_min": 0.55,
        },
        "weights": {"trend": 20, "demand": 15, "heat": 10, "long_term": 35, "liquidity": 20},
        "flags": {
            "use_ma200_weight": True,
            "use_dividend_event": True,
            "suppress_minor_alerts": False,
        },
        "strong_alerts": ["cross_down_ma200", "trend_change_to_down", "sharp_drop_high_volume"],
        "weak_alerts": ["cross_up_ma200", "near_ytd_high_breakout"],
        "is_active": True,
    },
    {
        "profile_id": "system_small_growth",
        "profile_type": "SYSTEM",
        "profile_key": "small_growth",
        "base_profile_key": "small_growth",
        "name": "小型成長",
        "description": "小型成長。需給・25日線/75日線・高値接近を重視",
        "priority_order": 4,
        "manual_assign_recommended": False,
        "auto_assign": {
            "all": [
                {"market_cap_lt": 500000000000},
                {"avg_turnover_20d_gte": 100000000},
            ],
            "any": [
                {"volatility_20d_gte": 30.0},
                {"atr_pct_14_gte": 4.0},
                {"median_turnover_20d_gte": 100000000},
            ],
        },
        "thresholds": {
            "overheated_short": 18.0,
            "overheated_mid": 30.0,
            "liquidity_ok": 100000000,
            "volume_expanding": 1.8,
            "turnover_expanding": 1.8,
            "volume_spike": 2.0,
            "turnover_spike": 2.0,
            "ytd_high_near_ratio": 0.97,
            "near_ytd_high_breakout_ratio": 0.99,
            "near_ytd_high_breakout_turnover_ratio": 1.3,
            "sharp_drop_change_pct": -6.0,
            "sharp_drop_volume_ratio": 2.0,
            "sharp_drop_close_position_max": 0.35,
            "rebound_touch_band_pct": 2.0,
            "rebound_close_position_min": 0.60,
        },
        "weights": {"trend": 25, "demand": 35, "heat": 25, "long_term": 10, "liquidity": 5},
        "flags": {
            "use_ma200_weight": False,
            "use_dividend_event": False,
            "suppress_minor_alerts": False,
        },
        "strong_alerts": ["cross_down_ma75", "trend_change_to_down", "sharp_drop_high_volume"],
        "weak_alerts": ["near_ytd_high_breakout", "rebound_from_ma25", "rebound_after_pullback", "turnover_spike"],
        "is_active": True,
    },
)


def build_system_technical_profiles(applied_at: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in SYSTEM_TECHNICAL_PROFILES:
        copied = deepcopy(row)
        copied["created_at"] = applied_at
        copied["updated_at"] = applied_at
        rows.append(copied)
    return rows


def apply_system_technical_profile_seed(store: DocumentStore, *, applied_at: str) -> bool:
    if store.get_document(TECHNICAL_PROFILE_SEED_DOC_PATH) is not None:
        return False

    for row in build_system_technical_profiles(applied_at):
        doc_path = f"{COLLECTION_TECHNICAL_PROFILES}/{technical_profile_doc_id(str(row['profile_id']))}"
        store.set_document(doc_path, row, merge=False)

    store.set_document(
        TECHNICAL_PROFILE_SEED_DOC_PATH,
        {
            "id": TECHNICAL_PROFILE_SEED_ID,
            "profile_keys": list(TECHNICAL_PROFILE_KEYS),
            "profile_ids": [row["profile_id"] for row in SYSTEM_TECHNICAL_PROFILES],
            "applied_at": applied_at,
            "status": "completed",
        },
        merge=False,
    )
    return True

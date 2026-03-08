from __future__ import annotations

from dataclasses import dataclass

from kabu_per_bot.technical_profiles import TechnicalProfile


@dataclass(frozen=True)
class TechnicalProfileRuntimeSettings:
    overheated_short: float = 15.0
    overheated_mid: float = 25.0
    liquidity_ok: float = 100_000_000.0
    volume_expanding: float = 1.5
    turnover_expanding: float = 1.5
    volume_spike: float = 2.0
    turnover_spike: float = 2.0
    ytd_high_near_ratio: float = 0.97
    near_ytd_high_breakout_ratio: float = 0.99
    near_ytd_high_breakout_turnover_ratio: float = 1.2
    sharp_drop_change_pct: float = -5.0
    sharp_drop_volume_ratio: float = 2.0
    sharp_drop_close_position_max: float = 0.35
    rebound_touch_band_pct: float = 2.0
    rebound_close_position_min: float = 0.6
    suppress_minor_alerts: bool = False
    strong_alerts: tuple[str, ...] = ()
    weak_alerts: tuple[str, ...] = ()


def resolve_technical_profile_runtime_settings(profile: TechnicalProfile | None) -> TechnicalProfileRuntimeSettings:
    if profile is None:
        return TechnicalProfileRuntimeSettings()
    thresholds = profile.thresholds
    flags = profile.flags
    return TechnicalProfileRuntimeSettings(
        overheated_short=float(thresholds.get("overheated_short", 15.0)),
        overheated_mid=float(thresholds.get("overheated_mid", 25.0)),
        liquidity_ok=float(thresholds.get("liquidity_ok", 100_000_000.0)),
        volume_expanding=float(thresholds.get("volume_expanding", 1.5)),
        turnover_expanding=float(thresholds.get("turnover_expanding", 1.5)),
        volume_spike=float(thresholds.get("volume_spike", 2.0)),
        turnover_spike=float(thresholds.get("turnover_spike", 2.0)),
        ytd_high_near_ratio=float(thresholds.get("ytd_high_near_ratio", 0.97)),
        near_ytd_high_breakout_ratio=float(thresholds.get("near_ytd_high_breakout_ratio", 0.99)),
        near_ytd_high_breakout_turnover_ratio=float(
            thresholds.get("near_ytd_high_breakout_turnover_ratio", 1.2)
        ),
        sharp_drop_change_pct=float(thresholds.get("sharp_drop_change_pct", -5.0)),
        sharp_drop_volume_ratio=float(thresholds.get("sharp_drop_volume_ratio", 2.0)),
        sharp_drop_close_position_max=float(thresholds.get("sharp_drop_close_position_max", 0.35)),
        rebound_touch_band_pct=float(thresholds.get("rebound_touch_band_pct", 2.0)),
        rebound_close_position_min=float(thresholds.get("rebound_close_position_min", 0.6)),
        suppress_minor_alerts=bool(flags.get("suppress_minor_alerts", False)),
        strong_alerts=tuple(profile.strong_alerts),
        weak_alerts=tuple(profile.weak_alerts),
    )

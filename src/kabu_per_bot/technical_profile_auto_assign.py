from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from kabu_per_bot.market_data import MarketDataSource
from kabu_per_bot.technical import TechnicalIndicatorsDaily
from kabu_per_bot.technical_profiles import TechnicalProfile
from kabu_per_bot.watchlist import WatchlistItem


class WatchlistRepository(Protocol):
    def update(self, item: WatchlistItem) -> None:
        """Persist watchlist item."""


class TechnicalIndicatorsRepository(Protocol):
    def list_recent(self, ticker: str, *, limit: int) -> list[TechnicalIndicatorsDaily]:
        """List recent technical indicators."""


class TechnicalProfilesRepository(Protocol):
    def list_all(self, *, include_inactive: bool = True) -> list[TechnicalProfile]:
        """List profiles."""


@dataclass(frozen=True)
class TechnicalProfileAutoAssignResult:
    processed_tickers: int
    updated_tickers: int
    skipped_manual_override: int
    matched_tickers: int
    assignments: tuple[tuple[str, str], ...]


def auto_assign_technical_profiles(
    *,
    watchlist_items: list[WatchlistItem],
    watchlist_repo: WatchlistRepository,
    technical_indicators_repo: TechnicalIndicatorsRepository,
    technical_profiles_repo: TechnicalProfilesRepository,
    market_data_source: MarketDataSource,
    now_iso: str | None = None,
    allow_manual_fallback: bool = False,
) -> TechnicalProfileAutoAssignResult:
    profiles = [
        profile
        for profile in technical_profiles_repo.list_all(include_inactive=False)
        if profile.profile_type.value == "SYSTEM"
    ]
    profiles.sort(key=lambda profile: profile.priority_order if profile.priority_order is not None else 9999)

    updated_tickers = 0
    skipped_manual_override = 0
    matched_tickers = 0
    assignments: list[tuple[str, str]] = []
    resolved_now_iso = now_iso or datetime.now(timezone.utc).isoformat()

    for item in watchlist_items:
        if not item.is_active:
            continue
        if item.technical_profile_manual_override:
            skipped_manual_override += 1
            continue

        latest = _latest_indicators(technical_indicators_repo, item.ticker)
        if latest is None:
            continue
        snapshot = market_data_source.fetch_snapshot(item.ticker)
        facts = dict(latest.values)
        facts["market_cap"] = snapshot.market_cap

        matched_profile = _match_profile(profiles, facts=facts, allow_manual_fallback=allow_manual_fallback)
        if matched_profile is None:
            continue
        matched_tickers += 1
        assignments.append((item.ticker, matched_profile.profile_id))
        if item.technical_profile_id == matched_profile.profile_id:
            continue
        watchlist_repo.update(
            WatchlistItem(
                ticker=item.ticker,
                name=item.name,
                metric_type=item.metric_type,
                notify_channel=item.notify_channel,
                notify_timing=item.notify_timing,
                priority=item.priority,
                always_notify_enabled=item.always_notify_enabled,
                ai_enabled=item.ai_enabled,
                is_active=item.is_active,
                evaluation_enabled=item.evaluation_enabled,
                evaluation_notify_mode=item.evaluation_notify_mode,
                evaluation_top_n=item.evaluation_top_n,
                evaluation_min_strength=item.evaluation_min_strength,
                ir_urls=item.ir_urls,
                x_official_account=item.x_official_account,
                x_executive_accounts=item.x_executive_accounts,
                technical_profile_id=matched_profile.profile_id,
                technical_profile_manual_override=False,
                technical_profile_override_thresholds=item.technical_profile_override_thresholds,
                technical_profile_override_flags=item.technical_profile_override_flags,
                technical_profile_override_strong_alerts=item.technical_profile_override_strong_alerts,
                technical_profile_override_weak_alerts=item.technical_profile_override_weak_alerts,
                created_at=item.created_at,
                updated_at=resolved_now_iso,
            )
        )
        updated_tickers += 1

    return TechnicalProfileAutoAssignResult(
        processed_tickers=len([item for item in watchlist_items if item.is_active]),
        updated_tickers=updated_tickers,
        skipped_manual_override=skipped_manual_override,
        matched_tickers=matched_tickers,
        assignments=tuple(assignments),
    )


def _latest_indicators(repository: TechnicalIndicatorsRepository, ticker: str) -> TechnicalIndicatorsDaily | None:
    rows = repository.list_recent(ticker, limit=1)
    if not rows:
        return None
    return rows[0]


def _match_profile(
    profiles: list[TechnicalProfile],
    *,
    facts: dict[str, Any],
    allow_manual_fallback: bool,
) -> TechnicalProfile | None:
    for profile in profiles:
        auto_assign = profile.auto_assign
        if auto_assign.get("manual_only"):
            if allow_manual_fallback and _evaluate_rule_group(auto_assign.get("fallback_rule"), facts=facts):
                return profile
            continue
        if _evaluate_rule_group(auto_assign, facts=facts):
            return profile
    return None


def _evaluate_rule_group(rule_group: Any, *, facts: dict[str, Any]) -> bool:
    if not isinstance(rule_group, dict):
        return False
    all_rules = rule_group.get("all")
    any_rules = rule_group.get("any")
    all_ok = True if all_rules in (None, []) else _evaluate_condition_list(all_rules, facts=facts, require_all=True)
    any_ok = True if any_rules in (None, []) else _evaluate_condition_list(any_rules, facts=facts, require_all=False)
    return all_ok and any_ok


def _evaluate_condition_list(raw_conditions: Any, *, facts: dict[str, Any], require_all: bool) -> bool:
    if not isinstance(raw_conditions, list) or not raw_conditions:
        return False
    results = [_evaluate_condition(condition, facts=facts) for condition in raw_conditions if isinstance(condition, dict)]
    if not results:
        return False
    return all(results) if require_all else any(results)


def _evaluate_condition(condition: dict[str, Any], *, facts: dict[str, Any]) -> bool:
    key, threshold = next(iter(condition.items()))
    for suffix in ("_gte", "_lte", "_gt", "_lt"):
        if key.endswith(suffix):
            fact_key = key[: -len(suffix)]
            current = facts.get(fact_key)
            if current is None:
                return False
            current_value = float(current)
            threshold_value = float(threshold)
            if suffix == "_gte":
                return current_value >= threshold_value
            if suffix == "_lte":
                return current_value <= threshold_value
            if suffix == "_gt":
                return current_value > threshold_value
            if suffix == "_lt":
                return current_value < threshold_value
    return False

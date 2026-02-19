from __future__ import annotations

from dataclasses import dataclass
import hashlib

from kabu_per_bot.intelligence import AiInsight, IntelEvent, IntelKind
from kabu_per_bot.signal import SignalState
from kabu_per_bot.storage.firestore_schema import normalize_ticker


@dataclass(frozen=True)
class NotificationMessage:
    ticker: str
    category: str
    condition_key: str
    body: str
    is_strong: bool

    @property
    def payload_hash(self) -> str:
        return hashlib.sha1(self.body.encode("utf-8")).hexdigest()


def format_signal_message(
    *,
    ticker: str,
    company_name: str,
    state: SignalState,
    metric_value: float | None,
    median_1w: float | None,
    median_3m: float | None,
    median_1y: float | None,
) -> NotificationMessage:
    if not state.category or not state.combo:
        raise ValueError("signal category/combo is required for signal notifications")

    normalized_ticker = normalize_ticker(ticker)
    del metric_value, median_1w, median_3m, median_1y
    streak_days = max(1, state.streak_days)
    combo_label = _format_combo_label(state.combo, is_strong=state.is_strong)
    trend_icon = "🔥" if state.is_strong else "📉"
    body = f"【{state.category}】{normalized_ticker} {company_name} {combo_label} under（{streak_days}日連続） {trend_icon}"
    return NotificationMessage(
        ticker=normalized_ticker,
        category=state.category,
        condition_key=f"{state.metric_type.value}:{state.combo}",
        body=body,
        is_strong=state.is_strong,
    )


def format_signal_status_message(
    *,
    ticker: str,
    company_name: str,
    state: SignalState,
    metric_value: float | None,
    median_1w: float | None,
    median_3m: float | None,
    median_1y: float | None,
    insufficient_windows: list[str] | None = None,
) -> NotificationMessage:
    normalized_ticker = normalize_ticker(ticker)
    metric_label = state.metric_type.value
    normalized_insufficient = _normalize_insufficient_windows(insufficient_windows)
    if normalized_insufficient:
        level_key = f"INSUFFICIENT_{'+'.join(normalized_insufficient)}"
        level_label = f"判定不能（中央値不足: {'/'.join(normalized_insufficient)}）"
        discount_line = "割安通知: 判定保留"
    else:
        level_key, level_label = _status_level(state)
        discount_line = "割安通知: なし"
    body = "\n".join(
        [
            f"【{metric_label}状況】",
            f"{company_name} ({normalized_ticker})",
            f"📊 {metric_label}: {_fmt(metric_value)}",
            f"📚 中央値(1W/3M/1Y): {_fmt(median_1w)} / {_fmt(median_3m)} / {_fmt(median_1y)}",
            f"🧭 判定レベル: {level_label}",
            f"🔕 {discount_line}",
        ]
    )
    return NotificationMessage(
        ticker=normalized_ticker,
        category=f"{metric_label}状況",
        condition_key=f"{metric_label}:STATUS:{level_key}",
        body=body,
        is_strong=False,
    )


def format_earnings_message(
    *,
    ticker: str,
    company_name: str,
    earnings_date: str,
    earnings_time: str | None,
    category: str,
    quarter: str | None = None,
) -> NotificationMessage:
    if category not in {"今週決算", "明日決算"}:
        raise ValueError(f"unsupported earnings category: {category}")
    normalized_ticker = normalize_ticker(ticker)
    time_suffix = f" {earnings_time}" if earnings_time else ""
    quarter_value = (quarter or "").strip()
    if quarter_value:
        header = f"【{category.removesuffix('決算')}{quarter_value}決算】"
    else:
        header = f"【{category}】"
    body = f"{header}{normalized_ticker} {company_name} {earnings_date}{time_suffix}"
    return NotificationMessage(
        ticker=normalized_ticker,
        category=category,
        condition_key=f"EARNINGS:{earnings_date}",
        body=body,
        is_strong=False,
    )


def format_data_unknown_message(
    *,
    ticker: str,
    company_name: str,
    missing_fields: list[str],
    context: str,
) -> NotificationMessage:
    normalized_ticker = normalize_ticker(ticker)
    del context
    sorted_fields = _normalize_unknown_fields(missing_fields)
    labels = [_missing_field_to_label(field) for field in sorted_fields]
    body = f"【データ不明】{normalized_ticker} {company_name} {'/'.join(labels)}が取得できませんでした"
    return NotificationMessage(
        ticker=normalized_ticker,
        category="データ不明",
        condition_key=f"UNKNOWN:{','.join(sorted_fields)}",
        body=body,
        is_strong=False,
    )


def format_intel_update_message(
    *,
    ticker: str,
    company_name: str,
    event: IntelEvent,
) -> NotificationMessage:
    normalized_ticker = normalize_ticker(ticker)
    category = "IR更新" if event.kind is IntelKind.IR else "SNS注目"
    lines = [
        f"【{category}】{normalized_ticker} {company_name}",
        f"📝 {event.title}",
    ]
    if event.kind is IntelKind.SNS:
        summary = _trim_text(event.content, max_chars=140)
        if summary:
            lines.append(f"💬 要約: {summary}")
    lines.extend(
        [
            f"🔗 URL: {event.url}",
            f"🏷️ 種別: {event.source_label}",
        ]
    )
    body = "\n".join(lines)
    return NotificationMessage(
        ticker=normalized_ticker,
        category=category,
        condition_key=f"{event.kind.value}:{event.fingerprint}",
        body=body,
        is_strong=False,
    )


def format_ai_attention_message(
    *,
    ticker: str,
    company_name: str,
    event: IntelEvent,
    insight: AiInsight,
) -> NotificationMessage:
    normalized_ticker = normalize_ticker(ticker)
    evidence = " / ".join(insight.evidence_urls) if insight.evidence_urls else event.url
    body = "\n".join(
        [
            f"【AI注目】{normalized_ticker} {company_name} {insight.summary}",
            f"🔗 根拠：{evidence}",
            f"🏷️ 分類：IR={insight.ir_label} SNS={insight.sns_label} トーン={insight.tone}",
            f"🎯 確信度：{insight.confidence}",
        ]
    )
    return NotificationMessage(
        ticker=normalized_ticker,
        category="AI注目",
        condition_key=f"AI:{event.fingerprint}",
        body=body,
        is_strong=False,
    )


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"


def _trim_text(value: str, *, max_chars: int) -> str:
    normalized = " ".join(str(value).split()).strip()
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _status_level(state: SignalState) -> tuple[str, str]:
    under_flags = {
        "1Y": state.under_1y,
        "3M": state.under_3m,
        "1W": state.under_1w,
    }
    active_labels = [label for label, is_under in under_flags.items() if is_under]
    if not active_labels:
        return ("NONE", "下回りなし")
    joined = "+".join(active_labels)
    return (f"{joined}_ONLY", f"{joined}のみ下回り")


def _normalize_insufficient_windows(windows: list[str] | None) -> list[str]:
    if not windows:
        return []
    normalized = []
    seen: set[str] = set()
    for raw in windows:
        value = str(raw).strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _format_combo_label(combo: str, *, is_strong: bool) -> str:
    if is_strong:
        return "1Y 3M 1W"
    return combo.replace("+", " ")


def _normalize_unknown_fields(missing_fields: list[str]) -> list[str]:
    normalized = sorted({field.strip() for field in missing_fields if field.strip()})
    if normalized:
        return normalized
    return ["unknown"]


def _missing_field_to_label(field: str) -> str:
    mapping = {
        "eps_forecast": "予想EPS",
        "sales_forecast": "売上",
        "market_cap": "時価総額",
        "earnings_date": "決算日時",
        "close_price": "終値",
        "market_data_source": "市場データ",
        "ir_sns_source": "IR/SNS",
        "unknown": "必要データ",
    }
    return mapping.get(field, field)

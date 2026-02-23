from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

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
    signal_phase: str,
    metric_value: float | None,
    median_1w: float | None,
    median_3m: float | None,
    median_1y: float | None,
    earnings_days: int | None = None,
) -> NotificationMessage:
    if not state.category or not state.combo:
        raise ValueError("signal category/combo is required for signal notifications")

    normalized_ticker = normalize_ticker(ticker)
    normalized_phase = _normalize_signal_phase(signal_phase)
    metric_label = state.metric_type.value
    streak_days = max(1, state.streak_days)
    combo_label = _format_combo_label(state.combo, is_strong=state.is_strong)
    header_icon = "🔥" if state.is_strong else "📉"
    difference_line, divergence_line = _build_metric_difference_lines(
        metric_value=metric_value,
        median_1w=median_1w,
        median_3m=median_3m,
        median_1y=median_1y,
    )
    priority, recommended_action = _signal_conclusion(state=state, signal_phase=normalized_phase)
    conclusion_line = _build_conclusion_line(
        icon=header_icon,
        priority=priority,
        recommended_action=recommended_action,
        reason=f"{metric_label}={_fmt(metric_value)} / 乖離率({divergence_line})",
    )
    lines = [
        conclusion_line,
        "",
        f"　{normalized_ticker} {company_name}",
        f"　区分: [{normalized_phase}] {state.category}",
        f"　🎯 {combo_label} under（{streak_days}日連続）",
        f"　{metric_label}: {_fmt(metric_value)}",
        f"　中央値(1W/3M/1Y): {_fmt(median_1w)} / {_fmt(median_3m)} / {_fmt(median_1y)}",
        f"　差分(現在-中央値): {difference_line}",
        f"　乖離率: {divergence_line}",
    ]
    earnings_days_line = _build_earnings_days_line(earnings_days)
    if earnings_days_line:
        lines.append(earnings_days_line)
    body = "\n".join(lines)
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
    signal_phase: str | None = None,
    earnings_days: int | None = None,
) -> NotificationMessage:
    normalized_ticker = normalize_ticker(ticker)
    metric_label = state.metric_type.value
    normalized_insufficient = _normalize_insufficient_windows(insufficient_windows)
    normalized_phase = _normalize_signal_phase(signal_phase) if signal_phase else None
    if normalized_insufficient:
        level_key = f"INSUFFICIENT_{'+'.join(normalized_insufficient)}"
        level_label = f"判定不能（中央値不足: {'/'.join(normalized_insufficient)}）"
        discount_label = "判定保留"
    else:
        level_key, level_label = _status_level(state)
        discount_label = "なし"
    difference_line, divergence_line = _build_metric_difference_lines(
        metric_value=metric_value,
        median_1w=median_1w,
        median_3m=median_3m,
        median_1y=median_1y,
    )
    priority, recommended_action, reason = _status_conclusion(
        metric_label=metric_label,
        metric_value=metric_value,
        divergence_line=divergence_line,
        level_key=level_key,
        normalized_phase=normalized_phase,
        normalized_insufficient=normalized_insufficient,
    )
    lines = [
        _build_conclusion_line(
            icon="📘",
            priority=priority,
            recommended_action=recommended_action,
            reason=reason,
        ),
        f"　{metric_label}状況",
        f"　{company_name} ({normalized_ticker})",
    ]
    if normalized_phase:
        lines.append(f"　シグナル種別: {normalized_phase}")
    lines.extend(
        [
            "",
            f"　{metric_label}: {_fmt(metric_value)}",
            f"　中央値(1W/3M/1Y): {_fmt(median_1w)} / {_fmt(median_3m)} / {_fmt(median_1y)}",
            f"　差分(現在-中央値): {difference_line}",
            f"　乖離率: {divergence_line}",
            f"　🎯 判定レベル: {level_label}",
            f"　割安通知: {discount_label}",
        ]
    )
    earnings_days_line = _build_earnings_days_line(earnings_days)
    if earnings_days_line:
        lines.append(earnings_days_line)
    body = "\n".join(lines)
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
    earnings_days: int | None = None,
) -> NotificationMessage:
    normalized_ticker = normalize_ticker(ticker)
    del context
    sorted_fields = _normalize_unknown_fields(missing_fields)
    labels = [_missing_field_to_label(field) for field in sorted_fields]
    lines = [
        f"【データ不明】{normalized_ticker} {company_name} {'/'.join(labels)}が取得できませんでした",
        "次の確認: 通知ログで同銘柄の履歴を確認し、必要に応じて /ops から対象ジョブを再実行してください",
    ]
    earnings_days_line = _build_earnings_days_line(earnings_days)
    if earnings_days_line:
        lines.append(earnings_days_line)
    body = "\n".join(lines)
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
    if event.kind is IntelKind.SNS:
        summary = _trim_text(event.content, max_chars=180)
        status_line, point_line = _split_sns_summary(summary)
        source_badge = _sns_source_badge(event.source_label)
        lines = [
            f"🛰️ {category}",
            f"　{normalized_ticker} {company_name}",
            f"　投稿: {event.title} / ソース: {source_badge}",
        ]
        if status_line or point_line:
            lines.append("")
        if status_line:
            lines.append(f"　🎯 {status_line}")
        if point_line:
            lines.append(f"　要点: {point_line}")
        lines.extend(
            [
                "",
                f"　🔗 {event.url}",
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

    lines = [
        f"【{category}】{normalized_ticker} {company_name}",
        f"📝 {event.title}",
    ]
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


def _build_metric_difference_lines(
    *,
    metric_value: float | None,
    median_1w: float | None,
    median_3m: float | None,
    median_1y: float | None,
) -> tuple[str, str]:
    windows = (
        ("1W", median_1w),
        ("3M", median_3m),
        ("1Y", median_1y),
    )
    differences: list[str] = []
    divergence_rates: list[str] = []
    for label, median in windows:
        differences.append(f"{label} {_fmt_difference(metric_value=metric_value, median_value=median)}")
        divergence_rates.append(f"{label} {_fmt_divergence_rate(metric_value=metric_value, median_value=median)}")
    return (" / ".join(differences), " / ".join(divergence_rates))


def _fmt_difference(*, metric_value: float | None, median_value: float | None) -> str:
    if metric_value is None or median_value is None:
        return "N/A"
    return f"{metric_value - median_value:+.2f}"


def _fmt_divergence_rate(*, metric_value: float | None, median_value: float | None) -> str:
    if metric_value is None or median_value is None:
        return "N/A"
    base = abs(median_value)
    if base == 0:
        return "N/A"
    return f"{((metric_value - median_value) / base) * 100:+.1f}%"


def _build_conclusion_line(
    *,
    icon: str,
    priority: str,
    recommended_action: str,
    reason: str,
) -> str:
    return f"{icon} 優先度:{priority} / 推奨アクション:{recommended_action} / 根拠数値:{reason}"


def _signal_conclusion(*, state: SignalState, signal_phase: str) -> tuple[str, str]:
    if state.is_strong:
        return ("高", "優先確認")
    if signal_phase == "新規":
        return ("中", "監視開始")
    return ("中", "継続監視")


def _status_conclusion(
    *,
    metric_label: str,
    metric_value: float | None,
    divergence_line: str,
    level_key: str,
    normalized_phase: str | None,
    normalized_insufficient: list[str],
) -> tuple[str, str, str]:
    if normalized_insufficient:
        return (
            "中",
            "データ確認",
            f"{metric_label}={_fmt(metric_value)} / 乖離率({divergence_line}) / 中央値不足({'/'.join(normalized_insufficient)})",
        )
    if normalized_phase == "解除":
        return ("中", "通常監視へ移行", f"{metric_label}={_fmt(metric_value)} / 乖離率({divergence_line})")
    if level_key == "NONE":
        return ("低", "様子見", f"{metric_label}={_fmt(metric_value)} / 乖離率({divergence_line})")
    return ("中", "監視継続", f"{metric_label}={_fmt(metric_value)} / 乖離率({divergence_line})")


def _normalize_signal_phase(signal_phase: str) -> str:
    normalized = str(signal_phase).strip()
    if normalized not in {"新規", "継続", "解除"}:
        raise ValueError(f"unsupported signal_phase: {signal_phase}")
    return normalized


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


def _build_earnings_days_line(earnings_days: int | None) -> str | None:
    if earnings_days is None:
        return None
    if earnings_days <= 0:
        return "　📅 決算まで: 当日"
    return f"　📅 決算まで: {earnings_days}日"


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


def _split_sns_summary(summary: str) -> tuple[str, str]:
    normalized = " ".join(str(summary).split()).strip()
    if not normalized:
        return ("", "")

    matched = re.match(r"^\[(?P<meta>[^\]]+)\]\s*(?P<point>.*)$", normalized)
    if not matched:
        return ("", _normalize_sns_point(normalized))

    meta = _normalize_sns_meta(matched.group("meta"))
    point = _normalize_sns_point(matched.group("point"))
    return (meta, point)


def _normalize_sns_meta(meta: str) -> str:
    chunks = [chunk.strip() for chunk in str(meta).split("|") if chunk.strip()]
    if not chunks:
        return ""

    keyed: dict[str, str] = {}
    free_chunks: list[str] = []
    for chunk in chunks:
        matched = re.match(r"^(注目度|状況|Cat|影響)\s*[：:]\s*(.+)$", chunk, flags=re.I)
        if not matched:
            free_chunks.append(chunk)
            continue
        key = matched.group(1)
        value = matched.group(2).strip()
        if value:
            keyed[key] = f"{key}:{value}"

    ordered = [keyed[key] for key in ("注目度", "状況", "Cat", "影響") if key in keyed]
    ordered.extend(free_chunks)
    return " / ".join(ordered)


def _normalize_sns_point(point: str) -> str:
    normalized = " ".join(str(point).split()).strip()
    if not normalized:
        return ""
    normalized = re.sub(r"\s*\d+\s*(?:likes?|いいね)[。.．.]?$", "", normalized, flags=re.I).strip()
    return _trim_text(normalized, max_chars=120)


def _sns_source_badge(source_label: str) -> str:
    normalized = str(source_label).strip()
    if "公式" in normalized:
        return "🏢 公式"
    if "役員" in normalized:
        return f"👔 {normalized}"
    return f"🧩 {normalized or 'その他'}"


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

from __future__ import annotations

from dataclasses import dataclass
import hashlib

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
    metric_label = state.metric_type.value
    body = "\n".join(
        [
            f"【{state.category}】",
            f"{company_name} ({normalized_ticker})",
            f"{metric_label}: {_fmt(metric_value)}",
            f"中央値(1W/3M/1Y): {_fmt(median_1w)} / {_fmt(median_3m)} / {_fmt(median_1y)}",
            f"判定: {state.combo}",
            f"連続: {state.streak_days}日",
        ]
    )
    return NotificationMessage(
        ticker=normalized_ticker,
        category=state.category,
        condition_key=f"{state.metric_type.value}:{state.combo}",
        body=body,
        is_strong=state.is_strong,
    )


def format_earnings_message(
    *,
    ticker: str,
    company_name: str,
    earnings_date: str,
    earnings_time: str | None,
    category: str,
) -> NotificationMessage:
    if category not in {"今週決算", "明日決算"}:
        raise ValueError(f"unsupported earnings category: {category}")
    normalized_ticker = normalize_ticker(ticker)
    time_label = earnings_time or "未定"
    body = "\n".join(
        [
            f"【{category}】",
            f"{company_name} ({normalized_ticker})",
            f"決算予定: {earnings_date} {time_label}",
        ]
    )
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
    sorted_fields = sorted({field.strip() for field in missing_fields if field.strip()})
    if not sorted_fields:
        sorted_fields = ["unknown"]
    body = "\n".join(
        [
            "【データ不明】",
            f"{company_name} ({normalized_ticker})",
            f"欠損項目: {', '.join(sorted_fields)}",
            f"処理: {context}",
        ]
    )
    return NotificationMessage(
        ticker=normalized_ticker,
        category="データ不明",
        condition_key=f"UNKNOWN:{','.join(sorted_fields)}",
        body=body,
        is_strong=False,
    )


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"

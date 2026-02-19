from __future__ import annotations

from dataclasses import dataclass
import re


_HHMM_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_DEFAULT_PROMPT = (
    "以下の銘柄に関連する直近のSNS投稿を要約してください。\n"
    "- 重要度の高い話題を優先\n"
    "- 投稿日時・投稿者・URLを必ず含める\n"
    "- 憶測は避け、事実ベースで記述\n"
    "- 出力は日本語で簡潔に"
)


@dataclass(frozen=True)
class GrokSnsSettings:
    enabled: bool
    scheduled_time: str
    per_ticker_cooldown_hours: int
    prompt_template: str

    @classmethod
    def default(cls) -> "GrokSnsSettings":
        return cls(
            enabled=False,
            scheduled_time="21:10",
            per_ticker_cooldown_hours=24,
            prompt_template=_DEFAULT_PROMPT,
        )


def default_grok_prompt_template() -> str:
    return _DEFAULT_PROMPT


def validate_grok_sns_settings(value: GrokSnsSettings) -> None:
    if not _HHMM_PATTERN.fullmatch(value.scheduled_time.strip()):
        raise ValueError("scheduled_time must match HH:MM format.")
    if value.per_ticker_cooldown_hours <= 0:
        raise ValueError("per_ticker_cooldown_hours must be > 0.")
    if value.per_ticker_cooldown_hours > 168:
        raise ValueError("per_ticker_cooldown_hours must be <= 168.")
    if len(value.prompt_template.strip()) < 20:
        raise ValueError("prompt_template must be at least 20 characters.")
    if len(value.prompt_template) > 4000:
        raise ValueError("prompt_template must be <= 4000 characters.")

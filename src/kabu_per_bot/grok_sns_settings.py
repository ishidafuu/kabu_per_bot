from __future__ import annotations

from dataclasses import dataclass
import re


_HHMM_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_DEFAULT_PROMPT = (
    "以下の銘柄に直接関連するX投稿を抽出し、投資判断に有用な順で要約してください。\n"
    "- 公式発表・役員発言・一次情報を優先\n"
    "- 憶測や煽りは除外し、事実ベースで記述\n"
    "- summary は次の形式を厳守: [注目度:H/M/L|状況:改善/継続/悪化/不明|Cat:有/無(内容)|影響:↑/→/↓] 要点\n"
    "- 要点は80文字以内、likes/再生数/RT数など反応数は含めない"
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

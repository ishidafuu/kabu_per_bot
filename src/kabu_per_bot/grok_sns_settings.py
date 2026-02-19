from __future__ import annotations

from dataclasses import dataclass
import re


_HHMM_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_DEFAULT_PROMPT = (
    "{ticker} {company_name} に直接関連する X 投稿を抽出してください。\n"
    "投資判断に有用なものを重要度順に選び、事実ベースで要約してください。\n"
    "対象は公式発表・役員発言・信頼できる一次情報を優先し、無関係な投稿は除外してください。\n"
    "\n"
    "summary には必ず以下をこの順で含めてください（120文字以内で簡潔に）:\n"
    "[注目度:H/M/L|状況:改善/継続/悪化/不明|Cat:有/無(内容)|影響:↑/→/↓] 要点\n"
    "\n"
    "判定ルール:\n"
    "- 注目度: 株価影響の大きさと確度で判断\n"
    "- 状況: 直近の事業・需給・ニュースフローの方向\n"
    "- Cat: 1〜4週間で材料化し得る具体要因の有無\n"
    "- 影響: 短期の価格圧力（上昇/中立/下落）\n"
    "\n"
    "優先トピック:\n"
    "決算、業績修正、受注、提携、製品発表、規制/行政処分、訴訟、需給\n"
    "\n"
    "禁止:\n"
    "憶測、断定、煽り、URLや投稿時刻が確認できない情報の採用"
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

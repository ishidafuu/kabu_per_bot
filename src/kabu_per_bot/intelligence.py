from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import html
import logging
import re
from typing import Any, Protocol
from urllib.parse import urljoin

import httpx

from kabu_per_bot.watchlist import WatchlistItem


LOGGER = logging.getLogger(__name__)


class IntelKind(str, Enum):
    IR = "IR"
    SNS = "SNS"


class IntelSourceError(RuntimeError):
    """Raised when intelligence source access failed."""


class AiAnalyzeError(RuntimeError):
    """Raised when AI analysis failed."""


@dataclass(frozen=True)
class IntelEvent:
    ticker: str
    kind: IntelKind
    title: str
    url: str
    published_at: str
    source_label: str
    content: str

    @property
    def fingerprint(self) -> str:
        # published_at はソース次第で実行時刻になるため、重複判定キーから除外する。
        raw = "|".join([self.ticker, self.kind.value, self.url.strip()])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AiInsight:
    summary: str
    evidence_urls: list[str]
    ir_label: str
    sns_label: str
    tone: str
    confidence: str


class IntelSource(Protocol):
    def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
        """Fetch recent IR/SNS events."""


class AiAnalyzer(Protocol):
    def analyze(self, *, item: WatchlistItem, event: IntelEvent) -> AiInsight:
        """Analyze event and return human-readable explanation."""


@dataclass(frozen=True)
class CompositeIntelSource:
    sources: tuple[IntelSource, ...]

    def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
        merged: list[IntelEvent] = []
        errors: list[str] = []
        for source in self.sources:
            try:
                merged.extend(source.fetch_events(item, now_iso=now_iso))
            except IntelSourceError as exc:
                source_name = source.__class__.__name__
                LOGGER.warning("IR/SNSソース取得失敗: ticker=%s source=%s error=%s", item.ticker, source_name, exc)
                errors.append(f"{source_name}: {exc}")
            except Exception as exc:
                source_name = source.__class__.__name__
                LOGGER.exception("IR/SNSソース予期せぬ失敗: ticker=%s source=%s", item.ticker, source_name)
                errors.append(f"{source_name}: {exc}")
        if errors and not merged:
            raise IntelSourceError("; ".join(errors))
        unique: dict[str, IntelEvent] = {}
        for event in merged:
            unique[event.fingerprint] = event
        return sorted(unique.values(), key=lambda row: row.published_at, reverse=True)


class IRWebsiteIntelSource:
    _HREF_PATTERN = re.compile(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", flags=re.I | re.S)

    def __init__(self, *, timeout_sec: float = 15.0, max_events_per_url: int = 5) -> None:
        self._timeout_sec = timeout_sec
        self._max_events_per_url = max_events_per_url
        self._client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; kabu-per-bot/1.0)",
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            },
            follow_redirects=True,
        )

    def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
        events: list[IntelEvent] = []
        for ir_url in item.ir_urls:
            page = self._request_text(url=ir_url, ticker=item.ticker)
            extracted = self._extract_events_from_page(
                ticker=item.ticker,
                page=page,
                base_url=ir_url,
                now_iso=now_iso,
            )
            events.extend(extracted[: self._max_events_per_url])
        return events

    def _request_text(self, *, url: str, ticker: str) -> str:
        try:
            response = self._client.get(url, timeout=self._timeout_sec)
            response.raise_for_status()
        except Exception as exc:
            raise IntelSourceError(f"IR取得失敗: ticker={ticker} url={url} reason={exc}") from exc
        body = response.text
        if not body.strip():
            raise IntelSourceError(f"IR取得失敗: ticker={ticker} url={url} reason=empty_body")
        return body

    def _extract_events_from_page(
        self,
        *,
        ticker: str,
        page: str,
        base_url: str,
        now_iso: str,
    ) -> list[IntelEvent]:
        events: list[IntelEvent] = []
        for href, label in self._HREF_PATTERN.findall(page):
            title = _normalize_title(label)
            if len(title) < 4:
                continue
            absolute_url = urljoin(base_url, href.strip())
            if not absolute_url.startswith("http"):
                continue
            events.append(
                IntelEvent(
                    ticker=ticker,
                    kind=IntelKind.IR,
                    title=title,
                    url=absolute_url,
                    published_at=now_iso,
                    source_label="IRサイト",
                    content=title,
                )
            )
        unique: dict[str, IntelEvent] = {}
        for event in events:
            unique[event.url] = event
        return list(unique.values())


class XApiIntelSource:
    def __init__(
        self,
        *,
        bearer_token: str,
        timeout_sec: float = 15.0,
        max_results: int = 5,
        api_base_url: str = "https://api.twitter.com/2",
    ) -> None:
        self._bearer_token = bearer_token.strip()
        self._timeout_sec = timeout_sec
        self._max_results = max_results
        self._api_base_url = api_base_url.rstrip("/")
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {self._bearer_token}" if self._bearer_token else "",
                "User-Agent": "kabu-per-bot/1.0",
            }
        )

    def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
        handles = _collect_x_handles(item)
        if not handles:
            return []
        if not self._bearer_token:
            raise IntelSourceError("SNS取得失敗: X_API_BEARER_TOKEN が未設定です")

        events: list[IntelEvent] = []
        for handle, label in handles:
            user_id = self._resolve_user_id(handle=handle, ticker=item.ticker)
            tweets = self._fetch_recent_tweets(user_id=user_id, ticker=item.ticker)
            for tweet in tweets:
                tweet_id = str(tweet.get("id", "")).strip()
                text = str(tweet.get("text", "")).strip()
                created_at = str(tweet.get("created_at", "")).strip() or now_iso
                if not tweet_id or not text:
                    continue
                events.append(
                    IntelEvent(
                        ticker=item.ticker,
                        kind=IntelKind.SNS,
                        title=f"@{handle}",
                        url=f"https://x.com/{handle}/status/{tweet_id}",
                        published_at=created_at,
                        source_label=label,
                        content=text,
                    )
                )
        unique: dict[str, IntelEvent] = {}
        for event in events:
            unique[event.url] = event
        return sorted(unique.values(), key=lambda row: row.published_at, reverse=True)

    def _resolve_user_id(self, *, handle: str, ticker: str) -> str:
        url = f"{self._api_base_url}/users/by/username/{handle}"
        try:
            response = self._client.get(
                url,
                params={"user.fields": "id,username,name"},
                timeout=self._timeout_sec,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise IntelSourceError(f"SNS取得失敗: ticker={ticker} handle={handle} reason={exc}") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        user_id = str(data.get("id", "")).strip() if isinstance(data, dict) else ""
        if not user_id:
            raise IntelSourceError(f"SNS取得失敗: ticker={ticker} handle={handle} reason=user_id_not_found")
        return user_id

    def _fetch_recent_tweets(self, *, user_id: str, ticker: str) -> list[dict[str, Any]]:
        url = f"{self._api_base_url}/users/{user_id}/tweets"
        try:
            response = self._client.get(
                url,
                params={
                    "max_results": str(self._max_results),
                    "exclude": "retweets,replies",
                    "tweet.fields": "created_at",
                },
                timeout=self._timeout_sec,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise IntelSourceError(f"SNS取得失敗: ticker={ticker} user_id={user_id} reason={exc}") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        normalized: list[dict[str, Any]] = []
        for row in data:
            if isinstance(row, dict):
                normalized.append(row)
        return normalized


class HeuristicAiAnalyzer:
    _POSITIVE_KEYWORDS = ("増収", "増益", "上方修正", "受注", "好調", "成長", "過去最高")
    _NEGATIVE_KEYWORDS = ("減収", "減益", "下方修正", "赤字", "訴訟", "不正", "遅延")

    def analyze(self, *, item: WatchlistItem, event: IntelEvent) -> AiInsight:
        text = " ".join([event.title, event.content]).strip()
        if not text:
            raise AiAnalyzeError("AI解析失敗: event text is empty")

        summary = _summarize_text(text, max_chars=120)
        tone = _detect_tone(text, positives=self._POSITIVE_KEYWORDS, negatives=self._NEGATIVE_KEYWORDS)
        confidence = _estimate_confidence(text)
        ir_label = _resolve_ir_label(event)
        sns_label = _resolve_sns_label(event)
        return AiInsight(
            summary=summary,
            evidence_urls=[event.url],
            ir_label=ir_label,
            sns_label=sns_label,
            tone=tone,
            confidence=confidence,
        )


def resolve_now_utc_iso(*, now_iso: str | None = None) -> str:
    if now_iso is None:
        return datetime.now(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(now_iso)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _collect_x_handles(item: WatchlistItem) -> list[tuple[str, str]]:
    handles: list[tuple[str, str]] = []
    seen: set[str] = set()
    if item.x_official_account:
        if item.x_official_account not in seen:
            seen.add(item.x_official_account)
            handles.append((item.x_official_account, "公式"))
    for executive in item.x_executive_accounts:
        if executive.handle in seen:
            continue
        seen.add(executive.handle)
        label = "役員"
        if executive.role:
            label = f"役員({executive.role})"
        handles.append((executive.handle, label))
    return handles


def _normalize_title(value: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", value)
    normalized = html.unescape(stripped)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _summarize_text(text: str, *, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _detect_tone(text: str, *, positives: tuple[str, ...], negatives: tuple[str, ...]) -> str:
    positive_hits = sum(1 for keyword in positives if keyword in text)
    negative_hits = sum(1 for keyword in negatives if keyword in text)
    if positive_hits > negative_hits:
        return "ポジ"
    if negative_hits > positive_hits:
        return "ネガ"
    return "ニュートラル"


def _estimate_confidence(text: str) -> str:
    if len(text) >= 140:
        return "High"
    if len(text) >= 80:
        return "Med"
    return "Low"


def _resolve_ir_label(event: IntelEvent) -> str:
    if event.kind is not IntelKind.IR:
        return "該当なし"
    lowered = event.title.lower()
    if "決算" in event.title or "financial" in lowered:
        return "決算資料"
    if "説明会" in event.title:
        return "説明会"
    return "適時開示"


def _resolve_sns_label(event: IntelEvent) -> str:
    if event.kind is not IntelKind.SNS:
        return "該当なし"
    if "公式" in event.source_label:
        return "公式"
    return "役員"

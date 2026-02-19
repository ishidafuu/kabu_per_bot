from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
import hashlib
import html
from io import BytesIO
import json
import logging
import re
from typing import Any, Callable, Protocol
from urllib.parse import unquote, urljoin, urlparse

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

    def __init__(
        self,
        *,
        timeout_sec: float = 15.0,
        max_events_per_url: int = 5,
        max_content_chars: int = 3000,
        max_pdf_pages: int = 8,
        http_client: Any | None = None,
    ) -> None:
        self._timeout_sec = timeout_sec
        self._max_events_per_url = max_events_per_url
        self._max_content_chars = max_content_chars
        self._max_pdf_pages = max_pdf_pages
        self._client = http_client or httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; kabu-per-bot/1.0)",
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            },
            follow_redirects=True,
        )

    def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
        events: list[IntelEvent] = []
        for ir_url in item.ir_urls:
            response = self._request_response(url=ir_url, ticker=item.ticker)
            content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
            if ir_url.lower().endswith(".pdf") or "application/pdf" in content_type:
                title = _build_direct_ir_title(ir_url)
                content = self._extract_content_from_response(
                    response=response,
                    ticker=item.ticker,
                    url=ir_url,
                    fallback_text=title,
                )
                published_at = _resolve_event_published_at(response=response, title=title, url=ir_url)
                if not published_at:
                    LOGGER.info("IR公開日時の推定に失敗: ticker=%s url=%s", item.ticker, ir_url)
                events.append(
                    IntelEvent(
                        ticker=item.ticker,
                        kind=IntelKind.IR,
                        title=title,
                        url=ir_url,
                        published_at=published_at,
                        source_label="IRサイト",
                        content=content,
                    )
                )
                continue

            page = response.text
            if not page.strip():
                raise IntelSourceError(f"IR取得失敗: ticker={item.ticker} url={ir_url} reason=empty_body")
            extracted = self._extract_events_from_page(
                ticker=item.ticker,
                page=page,
                base_url=ir_url,
            )
            events.extend(extracted)
        return events

    def _request_response(self, *, url: str, ticker: str):
        try:
            response = self._client.get(url, timeout=self._timeout_sec)
            response.raise_for_status()
        except Exception as exc:
            raise IntelSourceError(f"IR取得失敗: ticker={ticker} url={url} reason={exc}") from exc
        return response

    def _extract_events_from_page(
        self,
        *,
        ticker: str,
        page: str,
        base_url: str,
    ) -> list[IntelEvent]:
        candidates: list[tuple[int, str, str, str]] = []
        seen_urls: set[str] = set()
        for index, (href, label) in enumerate(self._HREF_PATTERN.findall(page)):
            title = _normalize_title(label)
            if len(title) < 4:
                continue
            absolute_url = urljoin(base_url, href.strip())
            if not absolute_url.startswith("http"):
                continue
            if absolute_url in seen_urls:
                continue
            seen_urls.add(absolute_url)
            guessed_published_at = _infer_published_at_from_text_or_url(text=title, url=absolute_url) or ""
            candidates.append((index, title, absolute_url, guessed_published_at))

        ranked = sorted(
            candidates,
            key=lambda row: (-_score_ir_candidate(title=row[1], url=row[2], base_url=base_url), row[0]),
        )
        selected = ranked[: self._max_events_per_url]

        events: list[IntelEvent] = []
        for _, title, absolute_url, guessed_published_at in selected:
            content, published_at = self._request_event_content(
                ticker=ticker,
                url=absolute_url,
                fallback_text=title,
                title=title,
            )
            normalized_published_at = published_at or guessed_published_at
            events.append(
                IntelEvent(
                    ticker=ticker,
                    kind=IntelKind.IR,
                    title=title,
                    url=absolute_url,
                    published_at=normalized_published_at,
                    source_label="IRサイト",
                    content=content,
                )
            )
        return events

    def _request_event_content(self, *, ticker: str, url: str, fallback_text: str, title: str) -> tuple[str, str]:
        try:
            response = self._request_response(url=url, ticker=ticker)
        except Exception as exc:
            LOGGER.warning("IR本文取得失敗: ticker=%s url=%s error=%s", ticker, url, exc)
            fallback_published_at = _infer_published_at_from_text_or_url(text=title, url=url) or ""
            return (fallback_text, fallback_published_at)

        content = self._extract_content_from_response(
            response=response,
            ticker=ticker,
            url=url,
            fallback_text=fallback_text,
        )
        published_at = _resolve_event_published_at(response=response, title=title, url=url)
        if not published_at:
            LOGGER.info("IR公開日時の推定に失敗: ticker=%s url=%s", ticker, url)
        return (content, published_at)

    def _extract_content_from_response(self, *, response: Any, ticker: str, url: str, fallback_text: str) -> str:
        try:
            content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
            if url.lower().endswith(".pdf") or "application/pdf" in content_type:
                extracted = _extract_pdf_text(
                    payload=response.content,
                    max_pages=self._max_pdf_pages,
                    ticker=ticker,
                    url=url,
                )
            else:
                extracted = _extract_html_text(response.text)
        except Exception as exc:
            LOGGER.warning("IR本文解析失敗: ticker=%s url=%s error=%s", ticker, url, exc)
            return fallback_text

        normalized = _normalize_content_text(extracted, max_chars=self._max_content_chars)
        if len(normalized) < 20:
            return fallback_text
        return normalized


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


class GrokPromptIntelSource:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        reasoning_model: str | None = None,
        prompt_template: str,
        api_base_url: str = "https://api.x.ai/v1",
        timeout_sec: float = 30.0,
        max_events_per_ticker: int = 5,
        fetch_gate: Callable[[WatchlistItem, str], bool] | None = None,
        http_client: Any | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._model = model.strip()
        self._reasoning_model = (reasoning_model or "").strip()
        self._prompt_template = prompt_template.strip()
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._max_events_per_ticker = max_events_per_ticker
        self._fetch_gate = fetch_gate
        self._client = http_client or httpx.Client(
            headers={
                "Authorization": f"Bearer {self._api_key}" if self._api_key else "",
                "Content-Type": "application/json",
                "User-Agent": "kabu-per-bot/1.0",
            }
        )

    def fetch_events(self, item: WatchlistItem, *, now_iso: str) -> list[IntelEvent]:
        if not self._api_key:
            raise IntelSourceError("SNS取得失敗: GROK_API_KEY が未設定です")
        if not self._model:
            raise IntelSourceError("SNS取得失敗: GROK_MODEL_FAST が未設定です")
        if self._fetch_gate is not None and not self._fetch_gate(item, now_iso):
            return []

        first_error: IntelSourceError | None = None
        try:
            # 1st: non-reasoning model for cost efficiency
            content = self._call_chat(model=self._model, item=item, now_iso=now_iso)
            events = self._parse_events(item=item, now_iso=now_iso, content=content)
            if events:
                return events
            # 投稿0件は異常ではないため、失敗扱いせず通知なしで終了する。
            return []
        except IntelSourceError as exc:
            first_error = exc

        # 2nd: reasoning model as fallback when parse/extraction or API call failed on 1st model.
        if self._reasoning_model and self._reasoning_model != self._model:
            try:
                content = self._call_chat(model=self._reasoning_model, item=item, now_iso=now_iso)
                events = self._parse_events(item=item, now_iso=now_iso, content=content)
                if events:
                    return events
                return []
            except IntelSourceError as exc:
                if first_error is not None:
                    raise IntelSourceError(f"{first_error}; fallback={exc}") from exc
                raise

        if first_error is not None:
            raise first_error
        return []

    def _call_chat(self, *, model: str, item: WatchlistItem, now_iso: str) -> str:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "あなたは日本株のSNS監視アシスタントです。"
                        "必ずJSONのみを返してください。推測や架空情報は禁止です。"
                    ),
                },
                {
                    "role": "user",
                    "content": _build_grok_prompt(
                        item=item,
                        now_iso=now_iso,
                        max_events=self._max_events_per_ticker,
                        template=self._prompt_template,
                    ),
                },
            ],
            "temperature": 0.1,
        }
        endpoint = f"{self._api_base_url}/chat/completions"
        try:
            response = self._client.post(endpoint, json=payload, timeout=self._timeout_sec)
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise IntelSourceError(f"SNS取得失敗: ticker={item.ticker} model={model} reason={exc}") from exc
        return _extract_chat_completion_text(body, ticker=item.ticker)

    def _parse_events(self, *, item: WatchlistItem, now_iso: str, content: str) -> list[IntelEvent]:
        parsed = _parse_grok_posts_json(content=content, ticker=item.ticker)
        return _build_sns_events_from_grok(
            item=item,
            parsed=parsed,
            now_iso=now_iso,
            max_events=self._max_events_per_ticker,
        )


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


class VertexGeminiAiAnalyzer:
    def __init__(
        self,
        *,
        project_id: str,
        location: str = "global",
        model: str = "gemini-2.0-flash-001",
        timeout_sec: float = 20.0,
        credentials_provider: Callable[[], tuple[str, str | None]] | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._project_id = project_id.strip()
        self._location = location.strip() or "global"
        self._model = model.strip() or "gemini-2.0-flash-001"
        self._timeout_sec = timeout_sec
        self._credentials_provider = credentials_provider or _default_vertex_credentials
        self._client = http_client or httpx.Client()

    def analyze(self, *, item: WatchlistItem, event: IntelEvent) -> AiInsight:
        try:
            token, inferred_project_id = self._credentials_provider()
        except AiAnalyzeError:
            raise
        except Exception as exc:
            raise AiAnalyzeError(f"AI解析失敗: Vertex AI 認証情報の取得に失敗しました: {exc}") from exc
        project_id = self._project_id or (inferred_project_id or "").strip()
        if not project_id:
            raise AiAnalyzeError(
                "AI解析失敗: project_id が未設定です。FIRESTORE_PROJECT_ID か ADC のデフォルトプロジェクトを設定してください。"
            )
        endpoint = (
            "https://aiplatform.googleapis.com/v1/projects/"
            f"{project_id}/locations/{self._location}/publishers/google/models/{self._model}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": _build_vertex_prompt(item=item, event=event)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 400,
                "responseMimeType": "application/json",
            },
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            response = self._client.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=self._timeout_sec,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise AiAnalyzeError(f"AI解析失敗: Vertex AI API 呼び出しに失敗しました: {exc}") from exc
        return _build_ai_insight_from_vertex_response(event=event, payload=body)


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


def _build_grok_prompt(*, item: WatchlistItem, now_iso: str, max_events: int, template: str) -> str:
    handles = _collect_x_handles(item)
    official_handle = item.x_official_account or ""
    executive_handles = ", ".join([f"@{handle}" for handle, _ in handles if handle != official_handle])
    raw_template = template.strip()
    if not raw_template:
        raw_template = (
            "以下の銘柄に関連する直近SNS投稿を抽出し、重要度順に要約してください。"
            "投稿者・投稿時刻・URLを必ず付けてください。"
        )
    rendered = (
        raw_template.replace("{ticker}", item.ticker)
        .replace("{company_name}", item.name)
        .replace("{x_official_account}", official_handle or "(未設定)")
        .replace("{x_executive_accounts}", executive_handles or "(未設定)")
        .replace("{now_iso}", now_iso)
        .replace("{max_posts}", str(max_events))
    )
    return "\n".join(
        [
            rendered,
            "",
            f"対象銘柄: {item.ticker} {item.name}",
            f"公式アカウント: {official_handle or '(未設定)'}",
            f"役員アカウント: {executive_handles or '(未設定)'}",
            f"最大件数: {max_events}",
            "出力形式(JSONのみ):",
            '{"posts":[{"url":"https://x.com/...","published_at":"ISO8601","account":"@user","source_label":"公式|役員|その他","summary":"120文字以内"}]}',
            "投稿が見つからない場合も posts を空配列で返してください。",
        ]
    )


def _extract_chat_completion_text(payload: dict[str, Any], *, ticker: str) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise IntelSourceError(f"SNS取得失敗: ticker={ticker} reason=chat_choices_missing")
    first = choices[0]
    if not isinstance(first, dict):
        raise IntelSourceError(f"SNS取得失敗: ticker={ticker} reason=chat_choice_invalid")
    message = first.get("message")
    if not isinstance(message, dict):
        raise IntelSourceError(f"SNS取得失敗: ticker={ticker} reason=chat_message_missing")
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
    if isinstance(content, list):
        texts: list[str] = []
        for row in content:
            if isinstance(row, dict):
                text_value = str(row.get("text", "")).strip()
                if text_value:
                    texts.append(text_value)
        merged = "\n".join(texts).strip()
        if merged:
            return merged
    raise IntelSourceError(f"SNS取得失敗: ticker={ticker} reason=chat_content_empty")


def _parse_grok_posts_json(*, content: str, ticker: str) -> dict[str, Any]:
    normalized = content.strip()
    if normalized.startswith("```"):
        normalized = re.sub(r"^```(?:json)?\s*", "", normalized, flags=re.I)
        normalized = re.sub(r"\s*```$", "", normalized).strip()
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start < 0 or end <= start:
        raise IntelSourceError(f"SNS取得失敗: ticker={ticker} reason=json_extract_failed")
    candidate = normalized[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise IntelSourceError(f"SNS取得失敗: ticker={ticker} reason=json_decode_failed:{exc}") from exc
    if not isinstance(parsed, dict):
        raise IntelSourceError(f"SNS取得失敗: ticker={ticker} reason=json_root_not_object")
    return parsed


def _build_sns_events_from_grok(
    *,
    item: WatchlistItem,
    parsed: dict[str, Any],
    now_iso: str,
    max_events: int,
) -> list[IntelEvent]:
    rows = parsed.get("posts")
    if not isinstance(rows, list):
        return []

    events: list[IntelEvent] = []
    seen_urls: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url", "")).strip()
        if not url.startswith("http"):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        published_at = _normalize_published_at(value=row.get("published_at"), fallback_iso=now_iso)
        account = str(row.get("account", "")).strip() or "Grok SNS"
        source_label = str(row.get("source_label", "")).strip() or "Grok"
        summary = str(row.get("summary", "")).strip()
        if not summary:
            summary = account
        events.append(
            IntelEvent(
                ticker=item.ticker,
                kind=IntelKind.SNS,
                title=account,
                url=url,
                published_at=published_at,
                source_label=source_label,
                content=summary,
            )
        )
        if len(events) >= max_events:
            break
    return events


def _normalize_published_at(*, value: Any, fallback_iso: str) -> str:
    if value is None:
        return fallback_iso
    text = str(value).strip()
    if not text:
        return fallback_iso
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return fallback_iso
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


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


def _default_vertex_credentials() -> tuple[str, str | None]:
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ModuleNotFoundError as exc:
        raise AiAnalyzeError(
            "AI解析失敗: google-auth が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc
    try:
        credentials, project_id = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not getattr(credentials, "token", None):
            credentials.refresh(Request())
    except Exception as exc:
        raise AiAnalyzeError(f"AI解析失敗: Vertex AI 認証情報の取得に失敗しました: {exc}") from exc
    token = str(getattr(credentials, "token", "") or "").strip()
    if not token:
        raise AiAnalyzeError("AI解析失敗: Vertex AI 用アクセストークンの取得に失敗しました。")
    return (token, project_id)


def _build_vertex_prompt(*, item: WatchlistItem, event: IntelEvent) -> str:
    instructions = [
        "あなたは日本株のIR/SNS通知を要約するアシスタントです。",
        "入力情報から、通知で使う要約と分類をJSONのみで返してください。",
        "要件:",
        "- summary は120文字以内の日本語1文",
        "- evidence_urls は根拠URL配列（最低1件）",
        "- ir_label は 決算資料/適時開示/説明会/該当なし のいずれか",
        "- sns_label は 公式/役員/該当なし のいずれか",
        "- tone は ポジ/ニュートラル/ネガ のいずれか",
        "- confidence は High/Med/Low のいずれか",
        "出力形式:",
        '{"summary":"...","evidence_urls":["..."],"ir_label":"...","sns_label":"...","tone":"...","confidence":"..."}',
        "入力:",
        f"ticker: {item.ticker}",
        f"name: {item.name}",
        f"kind: {event.kind.value}",
        f"title: {event.title}",
        f"url: {event.url}",
        f"source_label: {event.source_label}",
        f"content: {event.content}",
    ]
    return "\n".join(instructions)


def _build_ai_insight_from_vertex_response(*, event: IntelEvent, payload: dict[str, Any]) -> AiInsight:
    text = _extract_vertex_text(payload)
    parsed = _parse_vertex_response_json(text)
    base_text = " ".join([event.title, event.content]).strip()
    summary = str(parsed.get("summary", "")).strip() or _summarize_text(base_text, max_chars=120)
    evidence_urls = _normalize_evidence_urls(parsed.get("evidence_urls"), fallback_url=event.url)
    ir_label = str(parsed.get("ir_label", "")).strip() or _resolve_ir_label(event)
    sns_label = str(parsed.get("sns_label", "")).strip() or _resolve_sns_label(event)
    tone = _normalize_tone(str(parsed.get("tone", "")).strip(), fallback_text=base_text)
    confidence = _normalize_confidence(str(parsed.get("confidence", "")).strip(), fallback_text=base_text)
    return AiInsight(
        summary=summary,
        evidence_urls=evidence_urls,
        ir_label=ir_label,
        sns_label=sns_label,
        tone=tone,
        confidence=confidence,
    )


def _extract_vertex_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise AiAnalyzeError("AI解析失敗: Vertex AI レスポンスに candidates がありません。")
    first = candidates[0]
    if not isinstance(first, dict):
        raise AiAnalyzeError("AI解析失敗: Vertex AI レスポンス形式が不正です。")
    content = first.get("content")
    if not isinstance(content, dict):
        raise AiAnalyzeError("AI解析失敗: Vertex AI レスポンスに content がありません。")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise AiAnalyzeError("AI解析失敗: Vertex AI レスポンスに parts がありません。")
    texts = [str(part.get("text", "")).strip() for part in parts if isinstance(part, dict) and part.get("text")]
    merged = "\n".join([row for row in texts if row]).strip()
    if not merged:
        raise AiAnalyzeError("AI解析失敗: Vertex AI レスポンスにテキストがありません。")
    return merged


def _parse_vertex_response_json(text: str) -> dict[str, Any]:
    normalized = text.strip()
    if normalized.startswith("```"):
        normalized = re.sub(r"^```(?:json)?\s*", "", normalized, flags=re.I)
        normalized = re.sub(r"\s*```$", "", normalized)
        normalized = normalized.strip()
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start < 0 or end <= start:
        raise AiAnalyzeError("AI解析失敗: Vertex AI レスポンスからJSONオブジェクトを抽出できません。")
    candidate = normalized[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AiAnalyzeError(f"AI解析失敗: Vertex AI JSONの解析に失敗しました: {exc}") from exc
    if not isinstance(parsed, dict):
        raise AiAnalyzeError("AI解析失敗: Vertex AI JSONがオブジェクト形式ではありません。")
    return parsed


def _normalize_evidence_urls(value: Any, *, fallback_url: str) -> list[str]:
    rows: list[str] = []
    if isinstance(value, list):
        for raw in value:
            url = str(raw).strip()
            if not url.startswith("http"):
                continue
            if url not in rows:
                rows.append(url)
    if fallback_url.startswith("http") and fallback_url not in rows:
        rows.insert(0, fallback_url)
    if not rows:
        rows = [fallback_url]
    return rows


def _normalize_tone(value: str, *, fallback_text: str) -> str:
    normalized = value.strip().lower()
    mapping = {
        "ポジ": "ポジ",
        "positive": "ポジ",
        "ネガ": "ネガ",
        "negative": "ネガ",
        "ニュートラル": "ニュートラル",
        "neutral": "ニュートラル",
    }
    if normalized in mapping:
        return mapping[normalized]
    return _detect_tone(
        fallback_text,
        positives=("増収", "増益", "上方修正", "受注", "好調", "成長", "過去最高"),
        negatives=("減収", "減益", "下方修正", "赤字", "訴訟", "不正", "遅延"),
    )


def _normalize_confidence(value: str, *, fallback_text: str) -> str:
    normalized = value.strip().upper()
    mapping = {
        "HIGH": "High",
        "MEDIUM": "Med",
        "MED": "Med",
        "LOW": "Low",
    }
    if normalized in mapping:
        return mapping[normalized]
    return _estimate_confidence(fallback_text)


def _extract_html_text(body: str) -> str:
    normalized = re.sub(r"<script[^>]*>.*?</script>", " ", body, flags=re.I | re.S)
    normalized = re.sub(r"<style[^>]*>.*?</style>", " ", normalized, flags=re.I | re.S)
    normalized = re.sub(r"<[^>]+>", " ", normalized)
    normalized = html.unescape(normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _extract_pdf_text(*, payload: bytes, max_pages: int, ticker: str, url: str) -> str:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise IntelSourceError(
            f"IR本文取得失敗: ticker={ticker} url={url} reason=pypdf_not_installed"
        ) from exc

    reader = PdfReader(BytesIO(payload))
    collected: list[str] = []
    for index, page in enumerate(reader.pages):
        if index >= max_pages:
            break
        text = page.extract_text() or ""
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            collected.append(text)
    return "\n".join(collected).strip()


def _normalize_content_text(text: str, *, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip()


def _build_direct_ir_title(url: str) -> str:
    path = urlparse(url).path
    filename = unquote(path.rsplit("/", 1)[-1]).strip()
    if filename.lower().endswith(".pdf"):
        filename = filename[:-4]
    if filename:
        return filename
    return "IR資料"


def _resolve_event_published_at(*, response: Any, title: str, url: str) -> str:
    headers = getattr(response, "headers", {}) or {}
    header_value = str(headers.get("last-modified", "")).strip()
    parsed_header = _parse_http_datetime_iso8601(header_value)
    if parsed_header:
        return parsed_header
    inferred = _infer_published_at_from_text_or_url(text=title, url=url)
    if inferred:
        return inferred
    return ""


def _parse_http_datetime_iso8601(value: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = parsedate_to_datetime(normalized)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _infer_published_at_from_text_or_url(*, text: str, url: str) -> str | None:
    haystacks = [text, unquote(urlparse(url).path), unquote(url)]
    patterns = (
        re.compile(r"(20\d{2})[./\-年](\d{1,2})[./\-月](\d{1,2})日?"),
        re.compile(r"(20\d{2})(\d{2})(\d{2})"),
    )
    for haystack in haystacks:
        for pattern in patterns:
            match = pattern.search(haystack)
            if not match:
                continue
            try:
                year = int(match.group(1))
                month = int(match.group(2))
                day = int(match.group(3))
                parsed = datetime(year=year, month=month, day=day, tzinfo=timezone.utc)
            except ValueError:
                continue
            return parsed.isoformat()
    return None


def _score_ir_candidate(*, title: str, url: str, base_url: str) -> int:
    title_l = title.lower()
    url_l = url.lower()
    score = 0

    if url_l.endswith(".pdf"):
        score += 6
    if _contains_any(
        title_l,
        (
            "決算",
            "説明資料",
            "決算短信",
            "適時開示",
            "有価証券",
            "financial",
            "earnings",
            "presentation",
            "results",
        ),
    ):
        score += 5
    if _contains_any(
        url_l,
        (
            "/ir/",
            "/investor",
            "/disclosure",
            "/results",
            "/earnings",
            "/financial",
            "/library",
            ".pdf",
        ),
    ):
        score += 4
    if _contains_any(title_l + " " + url_l, ("privacy", "recruit", "contact", "company", "profile", "map")):
        score -= 3

    base_host = urlparse(base_url).hostname or ""
    url_host = urlparse(url).hostname or ""
    if base_host and url_host and base_host == url_host:
        score += 1
    return score


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)

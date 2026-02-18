from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import html
from io import BytesIO
import json
import logging
import re
from typing import Any, Callable, Protocol
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
        candidates: list[tuple[str, str]] = []
        seen_urls: set[str] = set()
        for href, label in self._HREF_PATTERN.findall(page):
            title = _normalize_title(label)
            if len(title) < 4:
                continue
            absolute_url = urljoin(base_url, href.strip())
            if not absolute_url.startswith("http"):
                continue
            if absolute_url in seen_urls:
                continue
            seen_urls.add(absolute_url)
            candidates.append((title, absolute_url))
            if len(candidates) >= self._max_events_per_url:
                break

        events: list[IntelEvent] = []
        for title, absolute_url in candidates:
            content = self._request_event_content(ticker=ticker, url=absolute_url, fallback_text=title)
            events.append(
                IntelEvent(
                    ticker=ticker,
                    kind=IntelKind.IR,
                    title=title,
                    url=absolute_url,
                    published_at=now_iso,
                    source_label="IRサイト",
                    content=content,
                )
            )
        return events

    def _request_event_content(self, *, ticker: str, url: str, fallback_text: str) -> str:
        try:
            response = self._client.get(url, timeout=self._timeout_sec)
            response.raise_for_status()
        except Exception as exc:
            LOGGER.warning("IR本文取得失敗: ticker=%s url=%s error=%s", ticker, url, exc)
            return fallback_text

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
        token, inferred_project_id = self._credentials_provider()
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
    credentials, project_id = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not getattr(credentials, "token", None):
        credentials.refresh(Request())
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

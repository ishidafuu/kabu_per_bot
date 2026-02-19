from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

import httpx


class IrUrlSuggestionError(RuntimeError):
    """Raised when candidate suggestion failed."""


@dataclass(frozen=True)
class IrUrlCandidateDraft:
    url: str
    title: str
    reason: str
    confidence: str


@dataclass(frozen=True)
class IrUrlCandidate:
    url: str
    title: str
    reason: str
    confidence: str
    validation_status: str
    score: int
    http_status: int | None
    content_type: str


class IrUrlSuggestor(Protocol):
    def suggest(self, *, ticker: str, company_name: str, max_candidates: int) -> list[IrUrlCandidateDraft]:
        """Suggest IR URL candidates."""


class VertexAiIrUrlSuggestor:
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

    def suggest(self, *, ticker: str, company_name: str, max_candidates: int) -> list[IrUrlCandidateDraft]:
        if max_candidates <= 0:
            raise IrUrlSuggestionError("max_candidates must be > 0")

        try:
            token, inferred_project_id = self._credentials_provider()
        except IrUrlSuggestionError:
            raise
        except Exception as exc:
            raise IrUrlSuggestionError(f"認証情報取得に失敗しました: {exc}") from exc

        project_id = self._project_id or (inferred_project_id or "").strip()
        if not project_id:
            raise IrUrlSuggestionError("project_id が未設定です。")

        endpoint = (
            "https://aiplatform.googleapis.com/v1/projects/"
            f"{project_id}/locations/{self._location}/publishers/google/models/{self._model}:generateContent"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": _build_vertex_prompt(ticker=ticker, company_name=company_name, max_candidates=max_candidates)}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 800,
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
            raise IrUrlSuggestionError(f"Vertex AI 呼び出しに失敗しました: {exc}") from exc
        return _parse_vertex_response_candidates(body=body, max_candidates=max_candidates)


class IrUrlCandidateValidator:
    def __init__(
        self,
        *,
        timeout_sec: float = 15.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._timeout_sec = timeout_sec
        self._client = http_client or httpx.Client(
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; kabu-per-bot/1.0)",
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            },
        )

    def validate(self, draft: IrUrlCandidateDraft) -> IrUrlCandidate:
        url = draft.url.strip()
        if not url:
            return IrUrlCandidate(
                url=url,
                title=draft.title.strip() or "(タイトル不明)",
                reason="URLが空です",
                confidence=_normalize_confidence(draft.confidence),
                validation_status="INVALID",
                score=0,
                http_status=None,
                content_type="",
            )

        parsed = urlparse(url)
        if parsed.scheme.lower() != "https":
            return IrUrlCandidate(
                url=url,
                title=draft.title.strip() or "(タイトル不明)",
                reason="https URLのみ登録対象です",
                confidence=_normalize_confidence(draft.confidence),
                validation_status="INVALID",
                score=0,
                http_status=None,
                content_type="",
            )

        http_status: int | None = None
        content_type = ""
        final_url = url
        fetch_reason = ""
        try:
            response = self._client.get(url, timeout=self._timeout_sec)
            http_status = response.status_code
            final_url = str(response.url)
            content_type = str(response.headers.get("content-type", "")).lower()
            if response.status_code >= 400:
                fetch_reason = f"HTTP {response.status_code}"
        except Exception as exc:
            fetch_reason = f"取得失敗: {exc}"

        score = _score_url(url=final_url, content_type=content_type, http_status=http_status)
        validation_status = _resolve_validation_status(
            http_status=http_status,
            fetch_reason=fetch_reason,
            score=score,
        )

        reason_parts: list[str] = []
        if draft.reason.strip():
            reason_parts.append(draft.reason.strip())
        if fetch_reason:
            reason_parts.append(fetch_reason)
        if not reason_parts:
            reason_parts.append("機械検証を通過")

        return IrUrlCandidate(
            url=final_url,
            title=draft.title.strip() or "(タイトル不明)",
            reason=" / ".join(reason_parts),
            confidence=_normalize_confidence(draft.confidence),
            validation_status=validation_status,
            score=score,
            http_status=http_status,
            content_type=content_type,
        )


class IrUrlCandidateService:
    def __init__(self, *, suggestor: IrUrlSuggestor, validator: IrUrlCandidateValidator) -> None:
        self._suggestor = suggestor
        self._validator = validator

    def suggest_candidates(self, *, ticker: str, company_name: str, max_candidates: int = 5) -> list[IrUrlCandidate]:
        if max_candidates <= 0:
            raise ValueError("max_candidates must be > 0")
        drafts = self._suggestor.suggest(
            ticker=ticker,
            company_name=company_name,
            max_candidates=max_candidates,
        )
        validated: list[IrUrlCandidate] = []
        seen: set[str] = set()
        for draft in drafts:
            candidate = self._validator.validate(draft)
            normalized_url = candidate.url.strip()
            if not normalized_url:
                continue
            if normalized_url in seen:
                continue
            seen.add(normalized_url)
            validated.append(candidate)
        return sorted(
            validated,
            key=lambda row: (
                _validation_rank(row.validation_status),
                row.score,
                _confidence_rank(row.confidence),
            ),
            reverse=True,
        )[:max_candidates]


def _build_vertex_prompt(*, ticker: str, company_name: str, max_candidates: int) -> str:
    return "\n".join(
        [
            "あなたは日本株IRページ調査アシスタントです。",
            "入力企業について、IR URL候補をJSONのみで返してください。",
            "推測のURLは禁止。実在する可能性が高いURLのみ提示してください。",
            f"ticker: {ticker}",
            f"company_name: {company_name}",
            f"max_candidates: {max_candidates}",
            "出力形式(JSONのみ):",
            (
                '{"candidates":['
                '{"url":"https://...","title":"...","reason":"...","confidence":"High|Med|Low"}'
                "]}"
            ),
        ]
    )


def _parse_vertex_response_candidates(*, body: dict[str, Any], max_candidates: int) -> list[IrUrlCandidateDraft]:
    text = _extract_vertex_text(body)
    parsed = _parse_json_object(text)
    rows = parsed.get("candidates")
    if not isinstance(rows, list):
        return []

    drafts: list[IrUrlCandidateDraft] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url", "")).strip()
        if not url:
            continue
        drafts.append(
            IrUrlCandidateDraft(
                url=url,
                title=str(row.get("title", "")).strip(),
                reason=str(row.get("reason", "")).strip(),
                confidence=_normalize_confidence(str(row.get("confidence", "")).strip()),
            )
        )
        if len(drafts) >= max_candidates:
            break
    return drafts


def _extract_vertex_text(body: dict[str, Any]) -> str:
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise IrUrlSuggestionError("Vertex AI レスポンスに candidates がありません。")
    first = candidates[0]
    if not isinstance(first, dict):
        raise IrUrlSuggestionError("Vertex AI レスポンス形式が不正です。")
    content = first.get("content")
    if not isinstance(content, dict):
        raise IrUrlSuggestionError("Vertex AI レスポンスに content がありません。")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise IrUrlSuggestionError("Vertex AI レスポンスに parts がありません。")
    texts = [str(part.get("text", "")).strip() for part in parts if isinstance(part, dict)]
    merged = "\n".join([row for row in texts if row]).strip()
    if not merged:
        raise IrUrlSuggestionError("Vertex AI レスポンスのテキスト抽出に失敗しました。")
    return merged


def _parse_json_object(text: str) -> dict[str, Any]:
    normalized = text.strip()
    if normalized.startswith("```"):
        normalized = re.sub(r"^```(?:json)?\s*", "", normalized, flags=re.I)
        normalized = re.sub(r"\s*```$", "", normalized).strip()
    start = normalized.find("{")
    end = normalized.rfind("}")
    if start < 0 or end <= start:
        raise IrUrlSuggestionError("レスポンスからJSONを抽出できませんでした。")
    candidate = normalized[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise IrUrlSuggestionError(f"JSON解析に失敗しました: {exc}") from exc
    if not isinstance(parsed, dict):
        raise IrUrlSuggestionError("レスポンスJSONがオブジェクト形式ではありません。")
    return parsed


def _default_vertex_credentials() -> tuple[str, str | None]:
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ModuleNotFoundError as exc:
        raise IrUrlSuggestionError(
            "google-auth が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
        ) from exc
    try:
        credentials, project_id = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not getattr(credentials, "token", None):
            credentials.refresh(Request())
    except Exception as exc:
        raise IrUrlSuggestionError(f"Vertex AI 認証情報の取得に失敗しました: {exc}") from exc
    token = str(getattr(credentials, "token", "") or "").strip()
    if not token:
        raise IrUrlSuggestionError("Vertex AI 用アクセストークンの取得に失敗しました。")
    return (token, project_id)


def _score_url(*, url: str, content_type: str, http_status: int | None) -> int:
    lowered_url = url.lower()
    lowered_ct = content_type.lower()
    score = 0
    if lowered_url.startswith("https://"):
        score += 1
    if _contains_any(
        lowered_url,
        (
            "/ir/",
            "/investor",
            "/disclosure",
            "/results",
            "/earnings",
            "/financial",
            "/library",
        ),
    ):
        score += 4
    if lowered_url.endswith(".pdf") or "application/pdf" in lowered_ct:
        score += 3
    if "text/html" in lowered_ct:
        score += 2
    if _contains_any(lowered_url, ("contact", "recruit", "privacy", "profile", "map")):
        score -= 3
    if http_status is not None and 200 <= http_status < 400:
        score += 1
    return score


def _resolve_validation_status(*, http_status: int | None, fetch_reason: str, score: int) -> str:
    if fetch_reason:
        return "INVALID"
    if http_status is None:
        return "INVALID"
    if http_status >= 400:
        return "INVALID"
    if score >= 5:
        return "VALID"
    return "WARNING"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _normalize_confidence(raw: str) -> str:
    normalized = raw.strip().upper()
    if normalized in {"HIGH", "H"}:
        return "High"
    if normalized in {"MED", "MEDIUM", "M"}:
        return "Med"
    if normalized in {"LOW", "L"}:
        return "Low"
    return "Med"


def _validation_rank(status: str) -> int:
    mapping = {
        "VALID": 3,
        "WARNING": 2,
        "INVALID": 1,
    }
    return mapping.get(status, 0)


def _confidence_rank(value: str) -> int:
    mapping = {
        "High": 3,
        "Med": 2,
        "Low": 1,
    }
    return mapping.get(value, 0)

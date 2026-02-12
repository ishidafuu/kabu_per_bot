from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol
import os

from fastapi import Header, Request

from kabu_per_bot.api.errors import ForbiddenError, InternalServerError, UnauthorizedError


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Mapping[str, Any]:
        """Verify token and return decoded claims."""


class FirebaseAdminTokenVerifier:
    def __init__(self) -> None:
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        try:
            import firebase_admin
        except ModuleNotFoundError as exc:
            raise InternalServerError(
                "firebase-admin が未インストールです。`pip install -e '.[gcp]'` を実行してください。"
            ) from exc

        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        self._initialized = True

    def verify(self, token: str) -> Mapping[str, Any]:
        self._ensure_initialized()
        try:
            from firebase_admin import auth
        except ModuleNotFoundError as exc:
            raise InternalServerError("firebase_admin.auth の読み込みに失敗しました。") from exc

        try:
            decoded = auth.verify_id_token(token, check_revoked=True)
            return dict(decoded)
        except Exception as exc:
            exc_name = exc.__class__.__name__
            if exc_name in {"RevokedIdTokenError", "UserDisabledError"}:
                raise ForbiddenError("このユーザーはAPIの利用が許可されていません。") from exc
            if exc_name in {
                "InvalidIdTokenError",
                "ExpiredIdTokenError",
                "CertificateFetchError",
                "InvalidArgumentError",
                "ValueError",
            }:
                raise UnauthorizedError("IDトークンの検証に失敗しました。") from exc
            raise UnauthorizedError("認証に失敗しました。") from exc


@dataclass(frozen=True)
class AuthContext:
    uid: str
    claims: Mapping[str, Any]


def parse_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise UnauthorizedError("Authorization ヘッダーが必要です。")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise UnauthorizedError("Authorization ヘッダーは Bearer トークン形式で指定してください。")
    return token.strip()


def _allowed_uids_from_env() -> set[str] | None:
    raw = os.getenv("API_ALLOWED_UIDS", "").strip()
    if not raw:
        return None
    values = {item.strip() for item in raw.split(",") if item.strip()}
    return values or None


def get_token_verifier(request: Request) -> TokenVerifier:
    verifier = getattr(request.app.state, "token_verifier", None)
    if verifier is not None:
        return verifier
    factory = getattr(request.app.state, "token_verifier_factory", None)
    if factory is None:
        raise RuntimeError("token_verifier が初期化されていません。")
    verifier = factory()
    request.app.state.token_verifier = verifier
    return verifier


def is_protected_path(path: str) -> bool:
    if path == "/api/v1/watchlist":
        return True
    return path.startswith("/api/v1/watchlist/")


def authenticate_request(
    request: Request,
    *,
    authorization_header: str | None = None,
) -> AuthContext:
    token = parse_bearer_token(authorization_header or request.headers.get("Authorization"))
    verifier = get_token_verifier(request)
    claims = verifier.verify(token)
    uid = str(claims.get("uid", "")).strip()
    if not uid:
        raise UnauthorizedError("IDトークンにuidが含まれていません。")

    allowed_uids = _allowed_uids_from_env()
    if allowed_uids is not None and uid not in allowed_uids:
        raise ForbiddenError("このユーザーは許可されていません。")
    return AuthContext(uid=uid, claims=claims)


def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthContext:
    return authenticate_request(request, authorization_header=authorization)

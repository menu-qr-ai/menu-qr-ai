import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette import status

from app.core.logging import redact_capability_path


SESSION_COOKIE_NAME = "hostai_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 12
SESSION_ID_KEY = "_session_id"
SESSION_CREATED_AT_KEY = "_session_created_at"
CSRF_TOKEN_KEY = "_csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_EXEMPT_PATHS = frozenset(
    {
        "/login",
        "/api/auth/login",
        "/api/analytics/events",
    }
)
CSRF_EXEMPT_PREFIXES = (
    "/api/customer/",
)
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

logger = logging.getLogger("app.web_security")


@dataclass(frozen=True)
class _DecodedSession:
    data: dict[str, Any]
    status: str


class SignedSessionMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        secret_key: str,
        https_only: bool,
        max_age: int = SESSION_MAX_AGE_SECONDS,
        trusted_origins: tuple[str, ...] = (),
    ) -> None:
        super().__init__(app)
        self.secret_key = secret_key.encode("utf-8")
        self.https_only = https_only
        self.max_age = max_age
        self.trusted_origins = {
            origin.rstrip("/").lower()
            for origin in trusted_origins
            if origin
        }

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw_cookie = request.cookies.get(SESSION_COOKIE_NAME)
        decoded = (
            self._decode(raw_cookie)
            if raw_cookie
            else _DecodedSession({}, "missing")
        )
        request.state.session = decoded.data
        request.state.session_status = decoded.status
        request.state.had_session_cookie = raw_cookie is not None
        if decoded.status == "valid" and decoded.data:
            ensure_session_security(decoded.data)
        if decoded.status in {"expired", "invalid"}:
            logger.warning(
                "web_session_rejected status=%s path=%s",
                decoded.status,
                redact_capability_path(request.url.path),
            )

        csrf_error = await self._validate_csrf(request)
        if csrf_error is not None:
            response: Response = csrf_error
        else:
            response = await call_next(request)
        self._apply_cookie(request, response, raw_cookie)
        return response

    async def _validate_csrf(
        self,
        request: Request,
    ) -> JSONResponse | None:
        session: dict[str, Any] = request.state.session
        if (
            request.method.upper() in SAFE_METHODS
            or request.url.path in CSRF_EXEMPT_PATHS
            or request.url.path.startswith(CSRF_EXEMPT_PREFIXES)
            or not isinstance(session.get("user_id"), int)
        ):
            return None

        origin = request.headers.get("origin")
        request_origin = (
            f"{request.url.scheme}://{request.url.netloc}"
        ).rstrip("/").lower()
        allowed_origins = {*self.trusted_origins, request_origin}
        if origin and origin.rstrip("/").lower() not in allowed_origins:
            return self._csrf_failure(request, "csrf_token_invalid")

        submitted = request.headers.get(CSRF_HEADER_NAME)
        if not submitted:
            submitted = await _csrf_token_from_form(request)
        if not submitted:
            return self._csrf_failure(request, "csrf_token_missing")

        expected = session.get(CSRF_TOKEN_KEY)
        if (
            not isinstance(expected, str)
            or not hmac.compare_digest(submitted, expected)
        ):
            return self._csrf_failure(request, "csrf_token_invalid")
        return None

    def _csrf_failure(
        self,
        request: Request,
        code: str,
    ) -> JSONResponse:
        logger.warning(
            "csrf_rejected method=%s path=%s code=%s",
            request.method,
            redact_capability_path(request.url.path),
            code,
        )
        message = (
            "Falta el token CSRF."
            if code == "csrf_token_missing"
            else "El token CSRF no es valido."
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "path": redact_capability_path(
                        request.url.path
                    ),
                }
            },
        )

    def _apply_cookie(
        self,
        request: Request,
        response: Response,
        raw_cookie: str | None,
    ) -> None:
        session: dict[str, Any] = request.state.session
        created_at = session.get(SESSION_CREATED_AT_KEY)
        now = int(time.time())
        remaining = (
            self.max_age - (now - created_at)
            if isinstance(created_at, int)
            else 0
        )
        if session and remaining > 0:
            response.set_cookie(
                SESSION_COOKIE_NAME,
                self._encode(session),
                max_age=remaining,
                expires=datetime.now(timezone.utc)
                + timedelta(seconds=remaining),
                httponly=True,
                secure=self.https_only,
                samesite="lax",
                path="/",
            )
        elif raw_cookie:
            response.delete_cookie(
                SESSION_COOKIE_NAME,
                path="/",
                secure=self.https_only,
                httponly=True,
                samesite="lax",
            )

    def _encode(self, session: dict[str, Any]) -> str:
        created_at = session.get(SESSION_CREATED_AT_KEY)
        if not isinstance(created_at, int):
            created_at = int(time.time())
            session[SESSION_CREATED_AT_KEY] = created_at
        payload = json.dumps(
            {
                "data": session,
                "issued_at": created_at,
                "expires_at": created_at + self.max_age,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded_payload = _encode_base64(payload)
        signature = hmac.new(
            self.secret_key,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{_encode_base64(signature)}"

    def _decode(self, value: str) -> _DecodedSession:
        try:
            encoded_payload, encoded_signature = value.split(".", 1)
            expected = hmac.new(
                self.secret_key,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(
                expected,
                _decode_base64(encoded_signature),
            ):
                return _DecodedSession({}, "invalid")
            payload = json.loads(_decode_base64(encoded_payload))
            issued_at = int(payload["issued_at"])
            expires_at = int(
                payload.get("expires_at", issued_at + self.max_age)
            )
            data = payload["data"]
            now = int(time.time())
            if issued_at > now + 60 or expires_at > issued_at + self.max_age:
                return _DecodedSession({}, "invalid")
            if now >= expires_at:
                return _DecodedSession({}, "expired")
            if not isinstance(data, dict):
                return _DecodedSession({}, "invalid")
            data.setdefault(SESSION_CREATED_AT_KEY, issued_at)
            return _DecodedSession(data, "valid")
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return _DecodedSession({}, "invalid")


def rotate_authenticated_session(
    session: dict[str, Any],
    user_id: int,
) -> None:
    session.clear()
    session["user_id"] = user_id
    session[SESSION_ID_KEY] = secrets.token_urlsafe(32)
    session[CSRF_TOKEN_KEY] = secrets.token_urlsafe(32)
    session[SESSION_CREATED_AT_KEY] = int(time.time())


def ensure_session_security(session: dict[str, Any]) -> None:
    session.setdefault(SESSION_ID_KEY, secrets.token_urlsafe(32))
    session.setdefault(CSRF_TOKEN_KEY, secrets.token_urlsafe(32))
    session.setdefault(SESSION_CREATED_AT_KEY, int(time.time()))


def ensure_csrf_token(session: dict[str, Any]) -> str:
    ensure_session_security(session)
    return str(session[CSRF_TOKEN_KEY])


def get_csrf_token(session: dict[str, Any]) -> str:
    token = session.get(CSRF_TOKEN_KEY)
    return token if isinstance(token, str) else ""


async def _csrf_token_from_form(request: Request) -> str | None:
    content_type = request.headers.get("content-type", "").lower()
    if "application/x-www-form-urlencoded" not in content_type:
        return None
    body = await request.body()
    _restore_request_body(request, body)
    values = parse_qs(
        body.decode("utf-8", errors="replace"),
        keep_blank_values=True,
    )
    tokens = values.get("csrf_token")
    return tokens[0] if tokens else None


def _restore_request_body(request: Request, body: bytes) -> None:
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }
        delivered = True
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    request._receive = receive


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))

import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        production: bool,
    ) -> None:
        super().__init__(app)
        self.production = production

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.csp_nonce = secrets.token_urlsafe(18)
        response = await call_next(request)
        self._apply_headers(request, response)
        return response

    def _apply_headers(
        self,
        request: Request,
        response: Response,
    ) -> None:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = (
            "strict-origin-when-cross-origin"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = self._csp(request)
        if self.production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        session = getattr(request.state, "session", {})
        has_authenticated_session = isinstance(
            session.get("user_id") if isinstance(session, dict) else None,
            int,
        )
        is_login = request.url.path in {"/login", "/api/auth/login"}
        is_customer_session = request.url.path.startswith(
            (
                "/menu/table/",
                "/menu/session/",
                "/api/customer/",
            )
        )
        if is_customer_session:
            response.headers["Referrer-Policy"] = "no-referrer"
        if (
            not request.url.path.startswith("/static/")
            and (
                has_authenticated_session
                or is_login
                or is_customer_session
                or getattr(request.state, "had_session_cookie", False)
            )
        ):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"

    def _csp(self, request: Request) -> str:
        if request.url.path in {"/docs", "/redoc"}:
            return (
                "default-src 'self' https://cdn.jsdelivr.net; "
                "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
                "img-src 'self' data: https:; "
                "style-src 'self' 'unsafe-inline' "
                "https://cdn.jsdelivr.net https://fonts.googleapis.com; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net"
            )
        nonce = request.state.csp_nonce
        return (
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "img-src 'self' data: https: http:; "
            "font-src 'self' https://fonts.gstatic.com; "
            "style-src 'self' 'unsafe-inline' "
            "https://fonts.googleapis.com; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "connect-src 'self'"
        )

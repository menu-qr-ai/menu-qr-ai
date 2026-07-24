import hashlib
import logging
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import LoginRateLimiter
from app.models import User
from app.services.auth_service import authenticate_user


logger = logging.getLogger("app.login_security")

login_rate_limiter = LoginRateLimiter(
    pair_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)


@dataclass(frozen=True)
class LoginAttempt:
    user: User | None
    retry_after: int

    @property
    def is_rate_limited(self) -> bool:
        return self.retry_after > 0


def attempt_login(
    db: Session,
    *,
    email: str,
    password: str,
    client_ip: str,
) -> LoginAttempt:
    normalized_email = email.strip().lower()
    email_fingerprint = hashlib.sha256(
        normalized_email.encode("utf-8")
    ).hexdigest()[:12]
    retry_after = login_rate_limiter.retry_after(
        client_ip,
        normalized_email,
    )
    if retry_after:
        logger.warning(
            "login_rate_limited ip=%s email_fingerprint=%s "
            "retry_after=%s",
            client_ip,
            email_fingerprint,
            retry_after,
        )
        return LoginAttempt(None, retry_after)

    user = authenticate_user(db, normalized_email, password)
    if user is None:
        login_rate_limiter.record_failure(
            client_ip,
            normalized_email,
        )
        logger.warning(
            "login_failed ip=%s email_fingerprint=%s",
            client_ip,
            email_fingerprint,
        )
        return LoginAttempt(None, 0)

    login_rate_limiter.clear_success(client_ip, normalized_email)
    logger.info(
        "login_succeeded ip=%s user_id=%s",
        client_ip,
        user.id,
    )
    return LoginAttempt(user, 0)


def client_ip_from_request(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.database import get_db
from app.models import User


logger = logging.getLogger("app.web_security")


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    session = getattr(request.state, "session", {})
    session_status = getattr(
        request.state,
        "session_status",
        "missing",
    )
    if session_status in {"expired", "invalid"}:
        return None
    user_id = session.get("user_id")
    if not isinstance(user_id, int):
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        session.clear()
        request.state.session_status = "invalid"
        logger.warning(
            "web_session_principal_invalid user_id=%s path=%s",
            user_id,
            request.url.path,
        )
        return None
    return user


def require_current_user(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    if current_user is None:
        session_status = getattr(
            request.state,
            "session_status",
            "missing",
        )
        error_code = {
            "expired": "session_expired",
            "invalid": "session_invalid",
        }.get(session_status, "authentication_required")
        message = (
            "La sesion ha expirado."
            if error_code == "session_expired"
            else "La sesion no es valida."
            if error_code == "session_invalid"
            else "Inicia sesion para continuar."
        )
        raise AppError(
            message,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=error_code,
        )
    return current_user


def require_web_user(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user)],
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": f"/login?next={request.url.path}"},
        )
    return current_user

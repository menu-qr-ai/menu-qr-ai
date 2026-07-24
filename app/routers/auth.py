import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.core.session import (
    get_csrf_token,
    rotate_authenticated_session,
)
from app.database import get_db
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.auth import AuthenticatedUserRead, LoginRequest
from app.core.access import role_home_path
from app.services.access_service import list_user_memberships
from app.services.login_security_service import (
    attempt_login,
    client_ip_from_request,
)


router = APIRouter(prefix="/api/auth", tags=["Authentication"])
logger = logging.getLogger("app.login_security")


@router.post("/login", response_model=AuthenticatedUserRead)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    attempt = attempt_login(
        db,
        email=payload.email,
        password=payload.password,
        client_ip=client_ip_from_request(request),
    )
    if attempt.is_rate_limited:
        raise AppError(
            "No se pudo iniciar sesion. Intentalo mas tarde.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="login_rate_limited",
            headers={"Retry-After": str(attempt.retry_after)},
        )
    if attempt.user is None:
        raise AppError(
            "Credenciales no validas.",
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_credentials",
        )
    user = attempt.user
    rotate_authenticated_session(request.state.session, user.id)
    memberships = list_user_memberships(db, user.id)
    if len(memberships) == 1:
        membership = memberships[0]
        request.state.session["active_restaurant_id"] = membership.restaurant_id
        next_url = role_home_path(membership.role)
    else:
        next_url = "/app/restaurants"
    return {
        "user": user,
        "next_url": next_url,
        "csrf_token": get_csrf_token(request.state.session),
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    user_id = request.state.session.get("user_id")
    request.state.session.clear()
    logger.info("logout_completed user_id=%s", user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=AuthenticatedUserRead)
def authenticated_user(
    request: Request,
    current_user: Annotated[User, Depends(require_current_user)],
):
    return {
        "user": current_user,
        "next_url": "/app",
        "csrf_token": get_csrf_token(request.state.session),
    }

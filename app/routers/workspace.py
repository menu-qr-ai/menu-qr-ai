import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from app.core.access import role_home_path
from app.core.session import (
    ensure_csrf_token,
    rotate_authenticated_session,
)
from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user, require_web_user
from app.models import User
from app.services.access_service import (
    get_access_context,
    select_active_restaurant,
)
from app.services.login_security_service import (
    attempt_login,
    client_ip_from_request,
)
from app.templates import templates


router = APIRouter(tags=["Workspace"])
logger = logging.getLogger("app.login_security")


@router.get("/login")
def login_page(
    request: Request,
    current_user: Annotated[User | None, Depends(get_current_user)],
    next_url: Annotated[str | None, Query(alias="next")] = None,
):
    if current_user is not None:
        return RedirectResponse("/app", status_code=status.HTTP_303_SEE_OTHER)
    ensure_csrf_token(request.state.session)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": None,
            "next_url": _safe_next_url(next_url),
        },
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next_url: Annotated[str | None, Form(alias="next")] = None,
    db: Session = Depends(get_db),
):
    attempt = attempt_login(
        db,
        email=email,
        password=password,
        client_ip=client_ip_from_request(request),
    )
    safe_next = _safe_next_url(next_url)
    if attempt.is_rate_limited:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": (
                    "No se pudo iniciar sesion. "
                    "Intentalo mas tarde."
                ),
                "next_url": safe_next,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(attempt.retry_after)},
        )
    if attempt.user is None:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Email o contraseña incorrectos.",
                "next_url": safe_next,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    user = attempt.user
    rotate_authenticated_session(request.state.session, user.id)
    memberships = get_access_context(db, user, None)["available_restaurants"]
    if len(memberships) == 1:
        membership = memberships[0]["membership"]
        request.state.session["active_restaurant_id"] = membership.restaurant_id
        destination = role_home_path(membership.role)
    else:
        destination = "/app/restaurants"
    if safe_next is not None:
        destination = safe_next
    return RedirectResponse(destination, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout_submit(request: Request):
    user_id = request.state.session.get("user_id")
    request.state.session.clear()
    logger.info("logout_completed user_id=%s", user_id)
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/app")
def app_home(
    current_user: Annotated[User, Depends(require_web_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    db: Session = Depends(get_db),
):
    context = get_access_context(db, current_user, active_restaurant_id)
    if context["membership"] is None:
        return RedirectResponse("/app/restaurants", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(context["next_url"], status_code=status.HTTP_303_SEE_OTHER)


@router.get("/app/restaurants")
def restaurant_selector(
    request: Request,
    current_user: Annotated[User, Depends(require_web_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request=request,
        name="restaurant_select.html",
        context=get_access_context(db, current_user, active_restaurant_id),
    )


@router.post("/app/restaurants/select")
def restaurant_selector_submit(
    request: Request,
    restaurant_id: Annotated[int, Form()],
    current_user: Annotated[User, Depends(require_web_user)],
    db: Session = Depends(get_db),
):
    membership = select_active_restaurant(
        db,
        current_user,
        restaurant_id,
        request.state.session,
    )
    return RedirectResponse(
        role_home_path(membership.role),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/app/waiter")
def waiter_home():
    return RedirectResponse("/staff/waiter", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/app/kitchen")
def kitchen_home():
    return RedirectResponse("/staff/kitchen", status_code=status.HTTP_303_SEE_OTHER)


def _safe_next_url(value: str | None) -> str | None:
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
    ):
        return None
    return value

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.core.version import APP_NAME, BUILD, VERSION
from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import require_web_user
from app.models import User
from app.services.access_service import authorize_restaurant, list_user_memberships, resolve_restaurant_access
from app.services.admin_service import get_admin_dashboard_data
from app.services.restaurant_service import require_restaurant
from app.templates import templates


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("")
def admin_dashboard(
    request: Request,
    current_user: Annotated[User, Depends(require_web_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        None,
        Permission.DASHBOARD_READ,
        active_restaurant_id=active_restaurant_id,
    )
    context = get_admin_dashboard_data(db, access.restaurant_id)
    context.update({"current_user": current_user, "current_membership": access})
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context=context,
    )


@router.get("/restaurants")
def admin_restaurants(
    request: Request,
    current_user: Annotated[User, Depends(require_web_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        None,
        Permission.RESTAURANT_MANAGE,
        active_restaurant_id=active_restaurant_id,
    )
    memberships = list_user_memberships(db, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="admin/restaurants.html",
        context={
            "restaurants": [membership.restaurant for membership in memberships],
            "memberships": memberships,
            "current_user": current_user,
            "current_membership": access,
            "app_version": {"name": APP_NAME, "version": VERSION, "build": BUILD},
        },
    )


@router.get("/restaurants/{restaurant_id}/settings")
def admin_restaurant_settings(
    restaurant_id: int,
    request: Request,
    current_user: Annotated[User, Depends(require_web_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    db: Session = Depends(get_db),
):
    authorize_restaurant(db, current_user, restaurant_id, Permission.RESTAURANT_MANAGE)
    active_membership = resolve_restaurant_access(
        db,
        current_user,
        None,
        Permission.RESTAURANT_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return templates.TemplateResponse(
        request=request,
        name="admin/restaurant_settings.html",
        context={
            "restaurant": require_restaurant(db, restaurant_id),
            "current_user": current_user,
            "current_membership": active_membership,
            "app_version": {"name": APP_NAME, "version": VERSION, "build": BUILD},
        },
    )

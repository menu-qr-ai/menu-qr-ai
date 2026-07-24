from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.core.version import APP_NAME, BUILD, VERSION
from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import require_current_user, require_web_user
from app.models import User
from app.schemas.dashboard import DashboardResponse
from app.services.access_service import list_user_memberships, resolve_restaurant_access
from app.services.dashboard_service import get_dashboard_summary
from app.templates import templates


router = APIRouter(tags=["Dashboard"])


@router.get("/api/dashboard/summary", response_model=DashboardResponse)
def dashboard_summary(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    range: str | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.DASHBOARD_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return get_dashboard_summary(db, restaurant_id=access.restaurant_id, range_value=range)


@router.get("/admin/dashboard")
def dashboard_page(
    request: Request,
    current_user: Annotated[User, Depends(require_web_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    range: str | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.DASHBOARD_READ,
        active_restaurant_id=active_restaurant_id,
    )
    memberships = list_user_memberships(db, current_user.id)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "restaurant_id": access.restaurant_id,
            "range": range or "30d",
            "restaurants": [membership.restaurant for membership in memberships],
            "current_membership": access,
            "current_user": current_user,
            "app_version": {"name": APP_NAME, "version": VERSION, "build": BUILD},
        },
    )

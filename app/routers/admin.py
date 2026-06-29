from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.version import APP_NAME, BUILD, VERSION
from app.database import get_db
from app.services.admin_service import get_admin_dashboard_data
from app.services.restaurant_service import list_restaurants, require_restaurant
from app.templates import templates


router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("")
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context=get_admin_dashboard_data(db),
    )


@router.get("/restaurants")
def admin_restaurants(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="admin/restaurants.html",
        context={
            "restaurants": list_restaurants(db),
            "app_version": {"name": APP_NAME, "version": VERSION, "build": BUILD},
        },
    )


@router.get("/restaurants/{restaurant_id}/settings")
def admin_restaurant_settings(restaurant_id: int, request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="admin/restaurant_settings.html",
        context={
            "restaurant": require_restaurant(db, restaurant_id),
            "app_version": {"name": APP_NAME, "version": VERSION, "build": BUILD},
        },
    )

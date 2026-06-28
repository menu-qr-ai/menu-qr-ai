from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import get_dashboard_summary
from app.services.restaurant_service import list_restaurants
from app.templates import templates


router = APIRouter(tags=["Dashboard"])


@router.get("/api/dashboard/summary", response_model=DashboardResponse)
def dashboard_summary(
    restaurant_id: int | None = None,
    range: str | None = None,
    db: Session = Depends(get_db),
):
    return get_dashboard_summary(db, restaurant_id=restaurant_id, range_value=range)


@router.get("/admin/dashboard")
def dashboard_page(
    request: Request,
    restaurant_id: int | None = None,
    range: str | None = None,
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"restaurant_id": restaurant_id, "range": range or "30d", "restaurants": list_restaurants(db)},
    )

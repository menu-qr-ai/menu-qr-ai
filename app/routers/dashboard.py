from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import get_dashboard_summary
from app.templates import templates


router = APIRouter(tags=["Dashboard"])


@router.get("/api/dashboard/summary", response_model=DashboardResponse)
def dashboard_summary(
    restaurant_id: int | None = None,
    db: Session = Depends(get_db),
):
    return get_dashboard_summary(db, restaurant_id=restaurant_id)


@router.get("/admin/dashboard")
def dashboard_page(
    request: Request,
    restaurant_id: int | None = None,
):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"restaurant_id": restaurant_id},
    )

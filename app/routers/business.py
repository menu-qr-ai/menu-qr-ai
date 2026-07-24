from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.business_insight import BusinessHealthScore, BusinessInsightReport, BusinessPriority
from app.services.business_insight_service import (
    get_business_health,
    get_business_insight_report,
    list_business_priorities,
)
from app.services.access_service import resolve_restaurant_access


router = APIRouter(prefix="/api/business", tags=["Business Insights"])


@router.get("/insights", response_model=BusinessInsightReport)
def business_insights(
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
    return get_business_insight_report(db, restaurant_id=access.restaurant_id, range_value=range)


@router.get("/health", response_model=BusinessHealthScore)
def business_health(
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
    return get_business_health(db, restaurant_id=access.restaurant_id, range_value=range)


@router.get("/priorities", response_model=list[BusinessPriority])
def business_priorities(
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
    return list_business_priorities(db, restaurant_id=access.restaurant_id, range_value=range)

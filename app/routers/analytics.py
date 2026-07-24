from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.analytics import AnalyticsEventCreate, AnalyticsEventRead
from app.services.analytics_event_service import count_events, create_event, list_recent_events
from app.services.access_service import resolve_restaurant_access


router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.post("/events", response_model=AnalyticsEventRead)
def create_analytics_event(
    payload: AnalyticsEventCreate,
    db: Session = Depends(get_db),
):
    return create_event(db, payload)


@router.get("/events/recent", response_model=list[AnalyticsEventRead])
def recent_analytics_events(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    restaurant_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.ANALYTICS_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return list_recent_events(db, restaurant_id=access.restaurant_id, limit=limit)


@router.get("/events/count")
def analytics_events_count(
    current_user: Annotated[User, Depends(require_current_user)],
    active_restaurant_id: Annotated[int | None, Depends(get_active_restaurant_id)],
    event_type: str | None = None,
    restaurant_id: int | None = None,
    db: Session = Depends(get_db),
):
    access = resolve_restaurant_access(
        db,
        current_user,
        restaurant_id,
        Permission.ANALYTICS_READ,
        active_restaurant_id=active_restaurant_id,
    )
    return {
        "count": count_events(db, event_type=event_type, restaurant_id=access.restaurant_id),
        "event_type": event_type,
        "restaurant_id": access.restaurant_id,
    }

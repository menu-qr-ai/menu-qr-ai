from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.analytics import AnalyticsEventCreate, AnalyticsEventRead
from app.services.analytics_event_service import count_events, create_event, list_recent_events


router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.post("/events", response_model=AnalyticsEventRead)
def create_analytics_event(
    payload: AnalyticsEventCreate,
    db: Session = Depends(get_db),
):
    return create_event(db, payload)


@router.get("/events/recent", response_model=list[AnalyticsEventRead])
def recent_analytics_events(
    restaurant_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return list_recent_events(db, restaurant_id=restaurant_id, limit=limit)


@router.get("/events/count")
def analytics_events_count(
    event_type: str | None = None,
    restaurant_id: int | None = None,
    db: Session = Depends(get_db),
):
    return {
        "count": count_events(db, event_type=event_type, restaurant_id=restaurant_id),
        "event_type": event_type,
        "restaurant_id": restaurant_id,
    }

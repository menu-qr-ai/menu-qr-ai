from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from starlette import status

from app.core.access import Permission
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.rate_limit import SlidingWindowRateLimiter
from app.database import get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import require_current_user
from app.models import User
from app.schemas.analytics import AnalyticsEventCreate, AnalyticsEventRead
from app.services.analytics_event_service import count_events, create_event, list_recent_events
from app.services.access_service import resolve_restaurant_access
from app.services.login_security_service import client_ip_from_request


router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

# Generous on purpose: a full restaurant behind one shared WiFi IP must fit.
analytics_rate_limiter = SlidingWindowRateLimiter(
    limit=settings.analytics_rate_limit_events,
    window_seconds=settings.analytics_rate_limit_window_seconds,
)


@router.post("/events", response_model=AnalyticsEventRead)
def create_analytics_event(
    payload: AnalyticsEventCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    retry_after = analytics_rate_limiter.hit(client_ip_from_request(request))
    if retry_after:
        raise AppError(
            "Demasiados eventos analytics. Intentalo mas tarde.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="analytics_rate_limited",
            headers={"Retry-After": str(retry_after)},
        )
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

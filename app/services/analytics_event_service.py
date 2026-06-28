import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.models import AnalyticsEvent
from app.schemas.analytics import AnalyticsEventCreate


ALLOWED_ANALYTICS_EVENTS = {
    "qr_scan",
    "menu_view",
    "language_change",
    "dish_view",
    "search",
    "ai_query",
    "translation_request",
}


def _serialize_metadata(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    return json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), default=str)


def _deserialize_metadata(metadata_json: str | None) -> dict[str, Any] | None:
    if not metadata_json:
        return None
    try:
        value = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def event_to_dict(event: AnalyticsEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "restaurant_id": event.restaurant_id,
        "event_type": event.event_type,
        "dish_id": event.dish_id,
        "language": event.language,
        "metadata": _deserialize_metadata(event.metadata_json),
        "created_at": event.created_at,
    }


def _validate_event_type(event_type: str) -> str:
    normalized = event_type.strip().lower()
    if normalized not in ALLOWED_ANALYTICS_EVENTS:
        raise AppError(
            "Tipo de evento analytics no permitido.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_analytics_event_type",
        )
    return normalized


def create_event(db: Session, payload: AnalyticsEventCreate) -> dict[str, Any]:
    event = AnalyticsEvent(
        restaurant_id=payload.restaurant_id,
        event_type=_validate_event_type(payload.event_type),
        dish_id=payload.dish_id,
        language=payload.language,
        metadata_json=_serialize_metadata(payload.metadata),
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event_to_dict(event)


def list_recent_events(
    db: Session,
    restaurant_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 100))
    statement = select(AnalyticsEvent).order_by(AnalyticsEvent.created_at.desc(), AnalyticsEvent.id.desc())
    if restaurant_id is not None:
        statement = statement.where(AnalyticsEvent.restaurant_id == restaurant_id)
    events = db.scalars(statement.limit(safe_limit)).all()
    return [event_to_dict(event) for event in events]


def count_events(
    db: Session,
    event_type: str | None = None,
    restaurant_id: int | None = None,
) -> int:
    statement = select(func.count()).select_from(AnalyticsEvent)
    if event_type:
        statement = statement.where(AnalyticsEvent.event_type == _validate_event_type(event_type))
    if restaurant_id is not None:
        statement = statement.where(AnalyticsEvent.restaurant_id == restaurant_id)
    return db.scalar(statement) or 0

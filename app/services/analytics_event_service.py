import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.models import AnalyticsEvent, Dish, Restaurant
from app.schemas.analytics import AnalyticsEventCreate


ALLOWED_ANALYTICS_EVENTS = {
    "qr_scan",
    "menu_view",
    "language_change",
    "dish_view",
    "search",
    "ai_query",
    "translation_request",
    "sale_processed",
}

# Events the anonymous public endpoint may record. Business events such as
# sale_processed are emitted only by internal services (fulfillment), because
# they feed predictions and business insights.
PUBLIC_ANALYTICS_EVENTS = frozenset(
    {
        "qr_scan",
        "menu_view",
        "language_change",
        "dish_view",
        "search",
        "translation_request",
    }
)
MAX_PUBLIC_METADATA_BYTES = 2048


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


def create_event_record(db: Session, payload: AnalyticsEventCreate) -> AnalyticsEvent:
    if payload.restaurant_id is not None:
        restaurant = db.get(Restaurant, payload.restaurant_id)
        if restaurant is None or not restaurant.is_active:
            raise AppError(
                "Restaurante no encontrado.",
                status_code=status.HTTP_404_NOT_FOUND,
                code="restaurant_not_found",
            )
    if payload.dish_id is not None:
        dish = db.scalar(
            select(Dish).where(
                Dish.id == payload.dish_id,
                Dish.restaurant_id == payload.restaurant_id,
            )
        )
        if dish is None:
            raise AppError(
                "Plato no encontrado para este restaurante.",
                status_code=status.HTTP_404_NOT_FOUND,
                code="dish_not_found",
            )
    event = AnalyticsEvent(
        restaurant_id=payload.restaurant_id,
        event_type=_validate_event_type(payload.event_type),
        dish_id=payload.dish_id,
        language=payload.language,
        metadata_json=_serialize_metadata(payload.metadata),
        created_at=datetime.utcnow(),
    )
    db.add(event)
    db.flush()
    db.refresh(event)
    return event


def _validate_public_payload(payload: AnalyticsEventCreate) -> None:
    if _validate_event_type(payload.event_type) not in PUBLIC_ANALYTICS_EVENTS:
        raise AppError(
            "Tipo de evento analytics no permitido.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_analytics_event_type",
        )
    serialized = _serialize_metadata(payload.metadata)
    if serialized is not None and len(serialized.encode("utf-8")) > MAX_PUBLIC_METADATA_BYTES:
        raise AppError(
            "Metadata analytics demasiado grande.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="analytics_metadata_too_large",
        )


def create_event(db: Session, payload: AnalyticsEventCreate) -> dict[str, Any]:
    _validate_public_payload(payload)
    event = create_event_record(db, payload)
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

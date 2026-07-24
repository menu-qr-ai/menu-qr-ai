from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission
from app.core.dining import ServiceSessionStatus
from app.core.exceptions import AppError
from app.core.orders import ACTIVE_ORDER_STATUSES, OrderStatus
from app.models import Order, ServiceSession, User
from app.schemas.dining import ServiceSessionOpen
from app.services.access_service import authorize_restaurant
from app.services.dining_room_service import require_table


def open_service_session(
    db: Session,
    actor: User,
    restaurant_id: int,
    table_id: int,
    payload: ServiceSessionOpen,
) -> ServiceSession:
    authorize_restaurant(db, actor, restaurant_id, Permission.SERVICE_SESSION_WRITE)
    table = require_table(db, restaurant_id, table_id)
    if not table.is_active:
        raise AppError(
            "No se puede abrir una sesion en una mesa inactiva.",
            status_code=status.HTTP_409_CONFLICT,
            code="table_inactive",
        )
    if table.zone is not None and not table.zone.is_active:
        raise AppError(
            "No se puede abrir una sesion en una zona inactiva.",
            status_code=status.HTTP_409_CONFLICT,
            code="zone_inactive",
        )
    if _get_open_session_for_table(db, restaurant_id, table_id) is not None:
        raise AppError(
            "La mesa ya tiene una sesion abierta.",
            status_code=status.HTTP_409_CONFLICT,
            code="table_already_occupied",
        )
    now = datetime.utcnow()
    service_session = ServiceSession(
        restaurant_id=restaurant_id,
        table_id=table_id,
        status=ServiceSessionStatus.OPEN.value,
        opened_at=now,
        guest_count=payload.guest_count,
        note=payload.note,
        opened_by_user_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(service_session)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            "La mesa ya tiene una sesion abierta.",
            status_code=status.HTTP_409_CONFLICT,
            code="table_already_occupied",
        ) from exc
    db.refresh(service_session)
    return service_session


def get_service_session(
    db: Session,
    actor: User,
    restaurant_id: int,
    session_id: int,
) -> ServiceSession:
    authorize_restaurant(db, actor, restaurant_id, Permission.DINING_ROOM_READ)
    return require_service_session(db, restaurant_id, session_id)


def close_service_session(
    db: Session,
    actor: User,
    restaurant_id: int,
    session_id: int,
) -> ServiceSession:
    authorize_restaurant(db, actor, restaurant_id, Permission.SERVICE_SESSION_WRITE)
    service_session = claim_open_service_session(
        db,
        restaurant_id,
        session_id,
    )
    return _finish_session(db, actor, service_session, ServiceSessionStatus.CLOSED)


def cancel_service_session(
    db: Session,
    actor: User,
    restaurant_id: int,
    session_id: int,
) -> ServiceSession:
    authorize_restaurant(db, actor, restaurant_id, Permission.SERVICE_SESSION_WRITE)
    service_session = claim_open_service_session(
        db,
        restaurant_id,
        session_id,
    )
    return _finish_session(db, actor, service_session, ServiceSessionStatus.CANCELLED)


def require_service_session(
    db: Session,
    restaurant_id: int,
    session_id: int,
) -> ServiceSession:
    service_session = db.scalar(
        select(ServiceSession)
        .options(selectinload(ServiceSession.table))
        .where(
            ServiceSession.id == session_id,
            ServiceSession.restaurant_id == restaurant_id,
        )
    )
    if service_session is None:
        raise AppError(
            "Sesion de servicio no encontrada para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="service_session_not_found",
        )
    return service_session


def claim_open_service_session(
    db: Session,
    restaurant_id: int,
    session_id: int,
) -> ServiceSession:
    now = datetime.utcnow()
    claim = db.execute(
        update(ServiceSession)
        .where(
            ServiceSession.id == session_id,
            ServiceSession.restaurant_id == restaurant_id,
            ServiceSession.status == ServiceSessionStatus.OPEN.value,
        )
        .values(updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        require_service_session(db, restaurant_id, session_id)
        raise AppError(
            "La sesion ya no esta abierta.",
            status_code=status.HTTP_409_CONFLICT,
            code="service_session_not_open",
        )
    db.expire_all()
    return require_service_session(db, restaurant_id, session_id)


def _finish_session(
    db: Session,
    actor: User,
    service_session: ServiceSession,
    next_status: ServiceSessionStatus,
) -> ServiceSession:
    if service_session.status != ServiceSessionStatus.OPEN.value:
        raise AppError(
            "La sesion ya no esta abierta.",
            status_code=status.HTTP_409_CONFLICT,
            code="service_session_not_open",
        )
    active_order = db.scalar(
        select(Order.id).where(
            Order.restaurant_id == service_session.restaurant_id,
            Order.service_session_id == service_session.id,
            Order.status.in_(ACTIVE_ORDER_STATUSES),
        )
    )
    if active_order is not None:
        raise AppError(
            "La sesion tiene pedidos activos; completalos o cancelalos antes de cerrarla.",
            status_code=status.HTTP_409_CONFLICT,
            code="service_session_has_active_orders",
        )
    completed_order = db.scalar(
        select(Order.id).where(
            Order.restaurant_id == service_session.restaurant_id,
            Order.service_session_id == service_session.id,
            Order.status == OrderStatus.COMPLETED.value,
        )
    )
    if completed_order is not None:
        raise AppError(
            "La sesion tiene pedidos completados y requiere settlement.",
            status_code=status.HTTP_409_CONFLICT,
            code="service_session_settlement_required",
        )
    now = datetime.utcnow()
    service_session.status = next_status.value
    service_session.closed_at = now
    service_session.closed_by_user_id = actor.id
    service_session.updated_at = now
    db.commit()
    db.refresh(service_session)
    return service_session


def _get_open_session_for_table(
    db: Session,
    restaurant_id: int,
    table_id: int,
) -> ServiceSession | None:
    return db.scalar(
        select(ServiceSession).where(
            ServiceSession.restaurant_id == restaurant_id,
            ServiceSession.table_id == table_id,
            ServiceSession.status == ServiceSessionStatus.OPEN.value,
        )
    )

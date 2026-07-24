from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission
from app.core.kitchen import KitchenStatus
from app.core.orders import OrderStatus
from app.core.exceptions import AppError
from app.models import KitchenTicket, KitchenTicketLine, Order, OrderLine, RestaurantTable, User
from app.services.access_service import authorize_restaurant


ACTIVE_KITCHEN_STATUSES = (
    KitchenStatus.PENDING.value,
    KitchenStatus.PREPARING.value,
    KitchenStatus.READY.value,
)


def list_kitchen_tickets(
    db: Session,
    actor: User,
    restaurant_id: int,
    *,
    ticket_status: KitchenStatus | None = None,
    active_only: bool = True,
) -> list[KitchenTicket]:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_READ)
    statement = (
        select(KitchenTicket)
        .options(
            selectinload(KitchenTicket.lines).selectinload(KitchenTicketLine.dish),
            selectinload(KitchenTicket.table).selectinload(RestaurantTable.zone),
        )
        .where(KitchenTicket.restaurant_id == restaurant_id)
        .order_by(KitchenTicket.created_at, KitchenTicket.id)
    )
    if ticket_status is not None:
        statement = statement.where(KitchenTicket.status == ticket_status.value)
    elif active_only:
        statement = statement.where(KitchenTicket.status.in_(ACTIVE_KITCHEN_STATUSES))
    return list(db.scalars(statement))


def get_kitchen_ticket(
    db: Session,
    actor: User,
    restaurant_id: int,
    ticket_id: int,
) -> KitchenTicket:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_READ)
    return require_kitchen_ticket(db, restaurant_id, ticket_id)


def get_order_kitchen_ticket(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
) -> KitchenTicket:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_READ)
    ticket = get_ticket_for_order_record(db, restaurant_id, order_id)
    if ticket is None:
        raise AppError(
            "El pedido todavia no tiene una comanda.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="kitchen_ticket_not_found",
        )
    return ticket


def start_kitchen_ticket(
    db: Session,
    actor: User,
    restaurant_id: int,
    ticket_id: int,
) -> KitchenTicket:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_OPERATE)
    ticket = require_kitchen_ticket(db, restaurant_id, ticket_id)
    if ticket.status not in (
        KitchenStatus.PENDING.value,
        KitchenStatus.PREPARING.value,
    ):
        _raise_invalid_transition()
    now = datetime.utcnow()
    for line in ticket.lines:
        if line.status == KitchenStatus.PENDING.value:
            _set_line_status(line, KitchenStatus.PREPARING, now)
    if ticket.started_at is None:
        ticket.started_at = now
    _recalculate_ticket_status(ticket, now)
    return _commit_ticket_action(db, ticket)


def start_kitchen_ticket_line(
    db: Session,
    actor: User,
    restaurant_id: int,
    ticket_id: int,
    line_id: int,
) -> KitchenTicket:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_OPERATE)
    ticket = require_kitchen_ticket(db, restaurant_id, ticket_id)
    line = require_kitchen_ticket_line(ticket, restaurant_id, line_id)
    if line.status == KitchenStatus.PREPARING.value:
        return ticket
    if line.status != KitchenStatus.PENDING.value:
        _raise_invalid_transition()
    now = datetime.utcnow()
    _set_line_status(line, KitchenStatus.PREPARING, now)
    _recalculate_ticket_status(ticket, now)
    return _commit_ticket_action(db, ticket)


def ready_kitchen_ticket_line(
    db: Session,
    actor: User,
    restaurant_id: int,
    ticket_id: int,
    line_id: int,
) -> KitchenTicket:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_OPERATE)
    ticket = require_kitchen_ticket(db, restaurant_id, ticket_id)
    line = require_kitchen_ticket_line(ticket, restaurant_id, line_id)
    if line.status == KitchenStatus.READY.value:
        return ticket
    if line.status != KitchenStatus.PREPARING.value:
        _raise_invalid_transition()
    now = datetime.utcnow()
    _set_line_status(line, KitchenStatus.READY, now)
    _recalculate_ticket_status(ticket, now)
    return _commit_ticket_action(db, ticket)


def ready_kitchen_ticket(
    db: Session,
    actor: User,
    restaurant_id: int,
    ticket_id: int,
) -> KitchenTicket:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_OPERATE)
    ticket = require_kitchen_ticket(db, restaurant_id, ticket_id)
    if ticket.status == KitchenStatus.READY.value:
        return ticket
    if ticket.status != KitchenStatus.PREPARING.value:
        _raise_invalid_transition()
    if any(line.status == KitchenStatus.PENDING.value for line in ticket.lines):
        raise AppError(
            "Inicia todas las lineas antes de marcar la comanda como lista.",
            status_code=status.HTTP_409_CONFLICT,
            code="kitchen_lines_pending",
        )
    now = datetime.utcnow()
    for line in ticket.lines:
        if line.status == KitchenStatus.PREPARING.value:
            _set_line_status(line, KitchenStatus.READY, now)
    _recalculate_ticket_status(ticket, now)
    return _commit_ticket_action(db, ticket)


def serve_kitchen_ticket(
    db: Session,
    actor: User,
    restaurant_id: int,
    ticket_id: int,
) -> KitchenTicket:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_OPERATE)
    ticket = require_kitchen_ticket(db, restaurant_id, ticket_id)
    if ticket.status == KitchenStatus.SERVED.value:
        return ticket
    if ticket.status != KitchenStatus.READY.value:
        _raise_invalid_transition()
    now = datetime.utcnow()
    for line in ticket.lines:
        if line.status == KitchenStatus.READY.value:
            _set_line_status(line, KitchenStatus.SERVED, now)
    _recalculate_ticket_status(ticket, now)
    return _commit_ticket_action(db, ticket)


def cancel_kitchen_ticket(
    db: Session,
    actor: User,
    restaurant_id: int,
    ticket_id: int,
) -> KitchenTicket:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_OPERATE)
    ticket = require_kitchen_ticket(db, restaurant_id, ticket_id)
    if ticket.status == KitchenStatus.CANCELLED.value:
        return ticket
    now = datetime.utcnow()
    cancel_kitchen_ticket_record(ticket, now)
    return _commit_ticket_action(db, ticket)


def cancel_kitchen_ticket_line(
    db: Session,
    actor: User,
    restaurant_id: int,
    ticket_id: int,
    line_id: int,
) -> KitchenTicket:
    authorize_restaurant(db, actor, restaurant_id, Permission.KITCHEN_OPERATE)
    ticket = require_kitchen_ticket(db, restaurant_id, ticket_id)
    line = require_kitchen_ticket_line(ticket, restaurant_id, line_id)
    if line.status == KitchenStatus.CANCELLED.value:
        return ticket
    if line.status not in (
        KitchenStatus.PENDING.value,
        KitchenStatus.PREPARING.value,
    ):
        _raise_invalid_transition()
    now = datetime.utcnow()
    _set_line_status(line, KitchenStatus.CANCELLED, now)
    _recalculate_ticket_status(ticket, now)
    return _commit_ticket_action(db, ticket)


def create_kitchen_ticket_record(
    db: Session,
    order: Order,
    actor: User,
) -> KitchenTicket:
    if order.status != OrderStatus.SUBMITTED.value:
        raise AppError(
            "Solo un pedido enviado puede generar una comanda.",
            status_code=status.HTTP_409_CONFLICT,
            code="order_not_submitted",
        )
    existing = get_ticket_for_order_record(db, order.restaurant_id, order.id)
    if existing is not None:
        return existing
    now = datetime.utcnow()
    ticket = KitchenTicket(
        restaurant_id=order.restaurant_id,
        order_id=order.id,
        service_session_id=order.service_session_id,
        table_id=order.service_session.table_id,
        status=KitchenStatus.PENDING.value,
        created_by_user_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    db.flush()
    _copy_order_lines(db, ticket, order.lines, now)
    db.flush()
    return ticket


def cancel_kitchen_ticket_record(
    ticket: KitchenTicket,
    now: datetime,
    *,
    allow_preparing: bool = True,
) -> None:
    if ticket.status == KitchenStatus.CANCELLED.value:
        return
    allowed_statuses = {KitchenStatus.PENDING.value}
    if allow_preparing:
        allowed_statuses.add(KitchenStatus.PREPARING.value)
    if ticket.status not in allowed_statuses or any(
        line.status in (
            KitchenStatus.READY.value,
            KitchenStatus.SERVED.value,
        )
        for line in ticket.lines
    ):
        raise AppError(
            "La comanda ya ha avanzado y no puede cancelarse.",
            status_code=status.HTTP_409_CONFLICT,
            code="kitchen_cancellation_not_allowed",
        )
    for line in ticket.lines:
        if line.status in (
            KitchenStatus.PENDING.value,
            KitchenStatus.PREPARING.value,
        ):
            _set_line_status(line, KitchenStatus.CANCELLED, now)
    _recalculate_ticket_status(ticket, now)


def require_kitchen_ticket(
    db: Session,
    restaurant_id: int,
    ticket_id: int,
) -> KitchenTicket:
    ticket = db.scalar(
        _ticket_statement().where(
            KitchenTicket.id == ticket_id,
            KitchenTicket.restaurant_id == restaurant_id,
        )
    )
    if ticket is None:
        raise AppError(
            "Comanda no encontrada para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="kitchen_ticket_not_found",
        )
    return ticket


def require_kitchen_ticket_line(
    ticket: KitchenTicket,
    restaurant_id: int,
    line_id: int,
) -> KitchenTicketLine:
    line = next(
        (
            candidate
            for candidate in ticket.lines
            if candidate.id == line_id
            and candidate.restaurant_id == restaurant_id
            and candidate.kitchen_ticket_id == ticket.id
        ),
        None,
    )
    if line is None:
        raise AppError(
            "Linea de comanda no encontrada para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="kitchen_ticket_line_not_found",
        )
    return line


def get_ticket_for_order_record(
    db: Session,
    restaurant_id: int,
    order_id: int,
) -> KitchenTicket | None:
    return db.scalar(
        _ticket_statement().where(
            KitchenTicket.order_id == order_id,
            KitchenTicket.restaurant_id == restaurant_id,
        )
    )


def _ticket_statement():
    return select(KitchenTicket).options(
        selectinload(KitchenTicket.lines).selectinload(KitchenTicketLine.dish),
        selectinload(KitchenTicket.table).selectinload(RestaurantTable.zone),
    )


def _copy_order_lines(
    db: Session,
    ticket: KitchenTicket,
    order_lines: list[OrderLine],
    now: datetime,
) -> None:
    for order_line in order_lines:
        db.add(
            KitchenTicketLine(
                restaurant_id=ticket.restaurant_id,
                kitchen_ticket_id=ticket.id,
                order_line_id=order_line.id,
                dish_id=order_line.dish_id,
                dish_name=order_line.dish_name,
                quantity=order_line.quantity,
                note=order_line.note,
                status=KitchenStatus.PENDING.value,
                created_at=now,
                updated_at=now,
            )
        )


def _set_line_status(
    line: KitchenTicketLine,
    next_status: KitchenStatus,
    now: datetime,
) -> None:
    line.status = next_status.value
    line.updated_at = now
    timestamp_field = {
        KitchenStatus.PREPARING: "started_at",
        KitchenStatus.READY: "ready_at",
        KitchenStatus.SERVED: "served_at",
        KitchenStatus.CANCELLED: "cancelled_at",
    }.get(next_status)
    if timestamp_field is not None and getattr(line, timestamp_field) is None:
        setattr(line, timestamp_field, now)


def _recalculate_ticket_status(ticket: KitchenTicket, now: datetime) -> None:
    statuses = {line.status for line in ticket.lines}
    if statuses == {KitchenStatus.CANCELLED.value}:
        next_status = KitchenStatus.CANCELLED
    elif statuses.issubset(
        {
            KitchenStatus.SERVED.value,
            KitchenStatus.CANCELLED.value,
        }
    ):
        next_status = KitchenStatus.SERVED
    elif statuses.issubset(
        {
            KitchenStatus.READY.value,
            KitchenStatus.SERVED.value,
            KitchenStatus.CANCELLED.value,
        }
    ):
        next_status = KitchenStatus.READY
    elif statuses & {
        KitchenStatus.PREPARING.value,
        KitchenStatus.READY.value,
        KitchenStatus.SERVED.value,
    }:
        next_status = KitchenStatus.PREPARING
    else:
        next_status = KitchenStatus.PENDING

    ticket.status = next_status.value
    ticket.updated_at = now
    timestamp_field = {
        KitchenStatus.PREPARING: "started_at",
        KitchenStatus.READY: "ready_at",
        KitchenStatus.SERVED: "served_at",
        KitchenStatus.CANCELLED: "cancelled_at",
    }.get(next_status)
    if timestamp_field is not None and getattr(ticket, timestamp_field) is None:
        setattr(ticket, timestamp_field, now)


def _commit_ticket_action(
    db: Session,
    ticket: KitchenTicket,
) -> KitchenTicket:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return require_kitchen_ticket(db, ticket.restaurant_id, ticket.id)


def _raise_invalid_transition() -> None:
    raise AppError(
        "La transicion de cocina no esta permitida.",
        status_code=status.HTTP_409_CONFLICT,
        code="kitchen_transition_invalid",
    )

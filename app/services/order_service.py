from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission
from app.core.exceptions import AppError
from app.core.kitchen import KitchenStatus
from app.core.money import normalize_money
from app.core.orders import OrderStatus
from app.models import Dish, Order, OrderFulfillment, OrderLine, User
from app.schemas.order import OrderCreate, OrderLineCreate, OrderLineUpdate
from app.services.access_service import authorize_restaurant
from app.services.customer_order_service import (
    validate_customer_order_availability,
)
from app.services.kitchen_ticket_service import (
    cancel_kitchen_ticket_record,
    create_kitchen_ticket_record,
    get_ticket_for_order_record,
)
from app.services.service_session_service import (
    claim_open_service_session,
    require_service_session,
)


def list_session_orders(
    db: Session,
    actor: User,
    restaurant_id: int,
    service_session_id: int,
) -> list[Order]:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_READ)
    require_service_session(db, restaurant_id, service_session_id)
    return list(
        db.scalars(
            select(Order)
            .options(
                selectinload(Order.lines),
                selectinload(Order.kitchen_ticket),
                selectinload(Order.fulfillment),
            )
            .where(
                Order.restaurant_id == restaurant_id,
                Order.service_session_id == service_session_id,
            )
            .order_by(Order.created_at, Order.id)
        )
    )


def get_order(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
) -> Order:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_READ)
    return require_order(db, restaurant_id, order_id)


def create_order(
    db: Session,
    actor: User,
    restaurant_id: int,
    service_session_id: int,
    payload: OrderCreate,
) -> Order:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_WRITE)
    claim_open_service_session(
        db,
        restaurant_id,
        service_session_id,
    )
    if payload.idempotency_key:
        existing = _get_order_by_idempotency_key(db, restaurant_id, payload.idempotency_key)
        if existing is not None:
            if existing.service_session_id != service_session_id:
                raise AppError(
                    "La clave de idempotencia ya pertenece a otra sesion.",
                    status_code=status.HTTP_409_CONFLICT,
                    code="order_idempotency_conflict",
                )
            return existing

    now = datetime.utcnow()
    order = Order(
        restaurant_id=restaurant_id,
        service_session_id=service_session_id,
        status=OrderStatus.DRAFT.value,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
        created_by_user_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    db.add(order)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if payload.idempotency_key:
            existing = _get_order_by_idempotency_key(db, restaurant_id, payload.idempotency_key)
            if existing is not None and existing.service_session_id == service_session_id:
                return existing
        raise AppError(
            "No se pudo crear el pedido.",
            status_code=status.HTTP_409_CONFLICT,
            code="order_conflict",
        ) from exc
    return require_order(db, restaurant_id, order.id)


def add_order_line(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
    payload: OrderLineCreate,
) -> Order:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_WRITE)
    order = require_order(db, restaurant_id, order_id)
    _require_draft_order(order)
    dish = _require_dish(db, restaurant_id, payload.dish_id)
    if dish.price is None:
        raise AppError(
            "El plato no tiene un precio configurado.",
            status_code=status.HTTP_409_CONFLICT,
            code="dish_price_missing",
        )
    if payload.idempotency_key:
        existing = _get_line_by_idempotency_key(db, order.id, payload.idempotency_key)
        if existing is not None:
            return order

    now = datetime.utcnow()
    db.add(
        OrderLine(
            restaurant_id=restaurant_id,
            order_id=order.id,
            dish_id=dish.id,
            dish_name=dish.name,
            quantity=payload.quantity,
            unit_price=normalize_money(
                dish.price,
                field_name="El precio del plato",
            ),
            note=payload.note,
            idempotency_key=payload.idempotency_key,
            created_at=now,
            updated_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if payload.idempotency_key and _get_line_by_idempotency_key(
            db,
            order.id,
            payload.idempotency_key,
        ):
            return require_order(db, restaurant_id, order_id)
        raise AppError(
            "No se pudo anadir la linea.",
            status_code=status.HTTP_409_CONFLICT,
            code="order_line_conflict",
        ) from exc
    return require_order(db, restaurant_id, order_id)


def update_order_line(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
    line_id: int,
    payload: OrderLineUpdate,
) -> Order:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_WRITE)
    order = require_order(db, restaurant_id, order_id)
    _require_draft_order(order)
    line = require_order_line(db, restaurant_id, order_id, line_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return order
    for field, value in changes.items():
        setattr(line, field, value)
    line.updated_at = datetime.utcnow()
    db.commit()
    return require_order(db, restaurant_id, order_id)


def delete_order_line(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
    line_id: int,
) -> None:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_WRITE)
    order = require_order(db, restaurant_id, order_id)
    _require_draft_order(order)
    line = require_order_line(db, restaurant_id, order_id, line_id)
    db.delete(line)
    db.commit()


def submit_order(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
) -> Order:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_WRITE)
    order = require_order(db, restaurant_id, order_id)
    if order.status == OrderStatus.SUBMITTED.value:
        if get_ticket_for_order_record(db, restaurant_id, order_id) is None:
            return _commit_order_submission(db, order, actor)
        return order
    _require_draft_order(order)
    if not order.lines:
        raise AppError(
            "No se puede enviar un pedido sin lineas.",
            status_code=status.HTTP_409_CONFLICT,
            code="order_empty",
        )
    now = datetime.utcnow()
    order.status = OrderStatus.SUBMITTED.value
    order.submitted_at = now
    order.updated_at = now
    return _commit_order_submission(db, order, actor)


def approve_customer_order(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
) -> Order:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.ORDER_WRITE,
    )
    order = require_order(db, restaurant_id, order_id)
    _require_customer_order(order)
    claim_open_service_session(
        db,
        restaurant_id,
        order.service_session_id,
    )
    order = require_order(db, restaurant_id, order_id)
    if order.status == OrderStatus.SUBMITTED.value:
        ticket = get_ticket_for_order_record(
            db,
            restaurant_id,
            order_id,
        )
        if order.reviewed_at is not None and ticket is not None:
            return order
    if order.status == OrderStatus.CANCELLED.value:
        raise AppError(
            "El pedido de cliente ya fue rechazado.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_already_rejected",
        )
    if order.status != OrderStatus.SUBMITTED_CUSTOMER.value:
        raise AppError(
            "El pedido de cliente no esta pendiente de aprobacion.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_not_reviewable",
        )
    if not order.lines:
        raise AppError(
            "No se puede aprobar un pedido sin platos.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_empty",
        )
    validate_customer_order_availability(db, order)
    now = datetime.utcnow()
    order.status = OrderStatus.SUBMITTED.value
    order.reviewed_by_user_id = actor.id
    order.reviewed_at = now
    order.rejection_reason = None
    order.updated_at = now
    return _commit_order_submission(db, order, actor)


def reject_customer_order(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
    *,
    reason: str | None,
) -> Order:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.ORDER_WRITE,
    )
    order = require_order(db, restaurant_id, order_id)
    _require_customer_order(order)
    if (
        order.status == OrderStatus.CANCELLED.value
        and order.reviewed_at is not None
    ):
        return order
    claim_open_service_session(
        db,
        restaurant_id,
        order.service_session_id,
    )
    order = require_order(db, restaurant_id, order_id)
    if (
        order.status == OrderStatus.CANCELLED.value
        and order.reviewed_at is not None
    ):
        return order
    if order.status == OrderStatus.SUBMITTED.value:
        raise AppError(
            "Un pedido ya aceptado no puede rechazarse.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_already_approved",
        )
    if order.status != OrderStatus.SUBMITTED_CUSTOMER.value:
        raise AppError(
            "El pedido de cliente no esta pendiente de aprobacion.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_not_reviewable",
        )
    now = datetime.utcnow()
    order.status = OrderStatus.CANCELLED.value
    order.cancelled_at = now
    order.reviewed_by_user_id = actor.id
    order.reviewed_at = now
    order.rejection_reason = reason
    order.updated_at = now
    db.commit()
    return require_order(db, restaurant_id, order_id)


def cancel_order(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
) -> Order:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_WRITE)
    order = require_order(db, restaurant_id, order_id)
    if order.status == OrderStatus.CANCELLED.value:
        return order
    if order.status == OrderStatus.COMPLETED.value:
        raise AppError(
            "Un pedido completado no puede cancelarse.",
            status_code=status.HTTP_409_CONFLICT,
            code="order_transition_invalid",
        )
    now = datetime.utcnow()
    ticket = get_ticket_for_order_record(db, restaurant_id, order_id)
    if order.status == OrderStatus.SUBMITTED.value and ticket is not None:
        cancel_kitchen_ticket_record(ticket, now, allow_preparing=False)
    order.status = OrderStatus.CANCELLED.value
    order.cancelled_at = now
    order.updated_at = now
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return require_order(db, restaurant_id, order_id)


def complete_order(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
) -> Order:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_WRITE)
    order = require_order(db, restaurant_id, order_id)
    if order.status == OrderStatus.COMPLETED.value:
        return order
    if order.status != OrderStatus.SUBMITTED.value:
        raise AppError(
            "Solo se puede completar un pedido enviado.",
            status_code=status.HTTP_409_CONFLICT,
            code="order_transition_invalid",
        )
    ticket = get_ticket_for_order_record(db, restaurant_id, order_id)
    if ticket is None or ticket.status != KitchenStatus.SERVED.value:
        raise AppError(
            "El pedido solo puede completarse cuando cocina lo ha marcado como servido.",
            status_code=status.HTTP_409_CONFLICT,
            code="kitchen_ticket_not_served",
        )
    fulfillment = db.scalar(
        select(OrderFulfillment).where(
            OrderFulfillment.restaurant_id == restaurant_id,
            OrderFulfillment.order_id == order_id,
            OrderFulfillment.status == "completed",
        )
    )
    if fulfillment is None:
        raise AppError(
            "El pedido debe completarse mediante fulfillment.",
            status_code=status.HTTP_409_CONFLICT,
            code="order_fulfillment_required",
        )
    now = datetime.utcnow()
    order.status = OrderStatus.COMPLETED.value
    order.completed_at = now
    order.updated_at = now
    db.commit()
    return require_order(db, restaurant_id, order_id)


def require_order(db: Session, restaurant_id: int, order_id: int) -> Order:
    order = db.scalar(
        select(Order)
        .options(
            selectinload(Order.lines),
            selectinload(Order.kitchen_ticket),
            selectinload(Order.fulfillment),
        )
        .where(
            Order.id == order_id,
            Order.restaurant_id == restaurant_id,
        )
    )
    if order is None:
        raise AppError(
            "Pedido no encontrado para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="order_not_found",
        )
    return order


def require_order_line(
    db: Session,
    restaurant_id: int,
    order_id: int,
    line_id: int,
) -> OrderLine:
    line = db.scalar(
        select(OrderLine).where(
            OrderLine.id == line_id,
            OrderLine.order_id == order_id,
            OrderLine.restaurant_id == restaurant_id,
        )
    )
    if line is None:
        raise AppError(
            "Linea de pedido no encontrada para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="order_line_not_found",
        )
    return line


def _require_draft_order(order: Order) -> None:
    if order.status != OrderStatus.DRAFT.value:
        raise AppError(
            "Solo se puede modificar un pedido en borrador.",
            status_code=status.HTTP_409_CONFLICT,
            code="order_not_editable",
        )


def _require_customer_order(order: Order) -> None:
    if order.customer_session_id is None:
        raise AppError(
            "El pedido no pertenece a una sesion de cliente.",
            status_code=status.HTTP_409_CONFLICT,
            code="customer_order_required",
        )


def _require_dish(db: Session, restaurant_id: int, dish_id: int) -> Dish:
    dish = db.scalar(
        select(Dish).where(
            Dish.id == dish_id,
            Dish.restaurant_id == restaurant_id,
        )
    )
    if dish is None:
        raise AppError(
            "Plato no encontrado para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="dish_not_found",
        )
    return dish


def _get_order_by_idempotency_key(
    db: Session,
    restaurant_id: int,
    idempotency_key: str,
) -> Order | None:
    return db.scalar(
        select(Order)
        .options(
            selectinload(Order.lines),
            selectinload(Order.kitchen_ticket),
            selectinload(Order.fulfillment),
        )
        .where(
            Order.restaurant_id == restaurant_id,
            Order.idempotency_key == idempotency_key,
        )
    )


def _get_line_by_idempotency_key(
    db: Session,
    order_id: int,
    idempotency_key: str,
) -> OrderLine | None:
    return db.scalar(
        select(OrderLine).where(
            OrderLine.order_id == order_id,
            OrderLine.idempotency_key == idempotency_key,
        )
    )


def _commit_order_submission(
    db: Session,
    order: Order,
    actor: User,
) -> Order:
    try:
        create_kitchen_ticket_record(db, order, actor)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        recovered_order = require_order(db, order.restaurant_id, order.id)
        recovered_ticket = get_ticket_for_order_record(
            db,
            order.restaurant_id,
            order.id,
        )
        if (
            recovered_order.status == OrderStatus.SUBMITTED.value
            and recovered_ticket is not None
        ):
            return recovered_order
        raise AppError(
            "No se pudo generar la comanda del pedido.",
            status_code=status.HTTP_409_CONFLICT,
            code="kitchen_ticket_conflict",
        ) from exc
    except Exception:
        db.rollback()
        raise
    return require_order(db, order.restaurant_id, order.id)

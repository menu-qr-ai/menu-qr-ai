import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission
from app.core.exceptions import AppError
from app.core.fulfillment import FulfillmentLineStatus, FulfillmentStatus
from app.core.kitchen import KitchenStatus
from app.core.orders import OrderStatus
from app.models import (
    KitchenTicket,
    KitchenTicketLine,
    Order,
    OrderFulfillment,
    OrderFulfillmentLine,
    User,
)
from app.schemas.fulfillment import (
    OrderFulfillmentLineRead,
    OrderFulfillmentRead,
)
from app.schemas.operational_transaction import SaleTransactionCreate
from app.services.access_service import authorize_restaurant
from app.services.operational_transaction_service import process_sale_transaction


logger = logging.getLogger("app.order_fulfillment")


_OPERATIONAL_ERROR_MAP = {
    "inventory_stock_negative": (
        "fulfillment_stock_insufficient",
        "No hay stock suficiente para cumplir el pedido.",
    ),
    "sale_cost_missing": (
        "fulfillment_cost_missing",
        "Falta el coste historico necesario para cumplir el pedido.",
    ),
    "recipe_empty": (
        "fulfillment_recipe_missing",
        "Un plato servido no tiene una receta tecnica disponible.",
    ),
}


def fulfill_order(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
) -> OrderFulfillmentRead:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_FULFILL)
    order = _require_order_for_fulfillment(db, restaurant_id, order_id)
    existing = _get_fulfillment(db, restaurant_id, order_id)
    if (
        existing is not None
        and existing.status == FulfillmentStatus.COMPLETED.value
    ):
        logger.info(
            "order_fulfillment_replay restaurant_id=%s order_id=%s "
            "fulfillment_id=%s",
            restaurant_id,
            order_id,
            existing.id,
        )
        return _to_schema(existing, is_idempotent_replay=True)

    served_lines, cancelled_lines = _validate_fulfillable(order)
    now = datetime.utcnow()
    fulfillment = existing
    fulfillment_id = existing.id if existing is not None else None
    claim_established = False
    try:
        if fulfillment is None:
            fulfillment = OrderFulfillment(
                restaurant_id=restaurant_id,
                order_id=order.id,
                status=FulfillmentStatus.PENDING.value,
                idempotency_key=_fulfillment_reference(
                    restaurant_id,
                    order.id,
                ),
                attempt_count=1,
                executed_by_user_id=actor.id,
                last_attempt_at=now,
                created_at=now,
                updated_at=now,
            )
            db.add(fulfillment)
            db.flush()
        else:
            claim = db.execute(
                update(OrderFulfillment)
                .where(
                    OrderFulfillment.id == fulfillment.id,
                    OrderFulfillment.status
                    == FulfillmentStatus.FAILED.value,
                )
                .values(
                    status=FulfillmentStatus.PENDING.value,
                    attempt_count=OrderFulfillment.attempt_count + 1,
                    executed_by_user_id=actor.id,
                    last_attempt_at=now,
                    failed_at=None,
                    error_code=None,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            if claim.rowcount != 1:
                db.rollback()
                concurrent = _get_fulfillment(
                    db,
                    restaurant_id,
                    order_id,
                )
                if (
                    concurrent is not None
                    and concurrent.status
                    == FulfillmentStatus.COMPLETED.value
                ):
                    logger.info(
                        "order_fulfillment_replay restaurant_id=%s "
                        "order_id=%s fulfillment_id=%s",
                        restaurant_id,
                        order_id,
                        concurrent.id,
                    )
                    return _to_schema(
                        concurrent,
                        is_idempotent_replay=True,
                    )
                raise AppError(
                    "El fulfillment del pedido esta siendo procesado.",
                    status_code=status.HTTP_409_CONFLICT,
                    code="fulfillment_conflict",
                )
            db.expire_all()
            fulfillment = _require_fulfillment(
                db,
                restaurant_id,
                order_id,
            )
        claim_established = True
        fulfillment_id = fulfillment.id
        logger.info(
            "order_fulfillment_started restaurant_id=%s order_id=%s "
            "fulfillment_id=%s",
            restaurant_id,
            order_id,
            fulfillment_id,
        )
        db.flush()
        _clear_stale_line_records(db, fulfillment)
        for ticket_line in served_lines:
            order_line = ticket_line.order_line
            operational_reference = _line_reference(
                restaurant_id,
                order.id,
                order_line.id,
            )
            result = process_sale_transaction(
                db,
                SaleTransactionCreate(
                    restaurant_id=restaurant_id,
                    dish_id=order_line.dish_id,
                    quantity=ticket_line.quantity,
                    occurred_at=ticket_line.served_at or now,
                    source="order_fulfillment",
                    reference=operational_reference,
                ),
            )
            db.add(
                OrderFulfillmentLine(
                    restaurant_id=restaurant_id,
                    fulfillment_id=fulfillment.id,
                    order_line_id=order_line.id,
                    kitchen_ticket_line_id=ticket_line.id,
                    dish_id=order_line.dish_id,
                    quantity=ticket_line.quantity,
                    status=FulfillmentLineStatus.PROCESSED.value,
                    operational_reference=operational_reference,
                    analytics_event_id=result.analytics_event_id,
                    movement_ids=result.movement_ids,
                    created_at=now,
                )
            )
        for ticket_line in cancelled_lines:
            order_line = ticket_line.order_line
            db.add(
                OrderFulfillmentLine(
                    restaurant_id=restaurant_id,
                    fulfillment_id=fulfillment.id,
                    order_line_id=order_line.id,
                    kitchen_ticket_line_id=ticket_line.id,
                    dish_id=order_line.dish_id,
                    quantity=ticket_line.quantity,
                    status=FulfillmentLineStatus.SKIPPED.value,
                    operational_reference=None,
                    analytics_event_id=None,
                    movement_ids=[],
                    created_at=now,
                )
            )

        fulfillment.status = FulfillmentStatus.COMPLETED.value
        fulfillment.completed_at = now
        fulfillment.updated_at = now
        order.status = OrderStatus.COMPLETED.value
        order.completed_at = now
        order.updated_at = now
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if claim_established:
            _record_failed_attempt(
                db,
                actor,
                restaurant_id,
                order_id,
                "fulfillment_transaction_failed",
            )
            logger.exception(
                "order_fulfillment_failed restaurant_id=%s order_id=%s "
                "fulfillment_id=%s "
                "error_code=fulfillment_transaction_failed",
                restaurant_id,
                order_id,
                fulfillment_id,
            )
            raise AppError(
                "No se pudo registrar la operacion del pedido.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="fulfillment_transaction_failed",
            ) from exc
        concurrent = _get_fulfillment(db, restaurant_id, order_id)
        if (
            concurrent is not None
            and concurrent.status == FulfillmentStatus.COMPLETED.value
        ):
            logger.info(
                "order_fulfillment_replay restaurant_id=%s order_id=%s "
                "fulfillment_id=%s",
                restaurant_id,
                order_id,
                concurrent.id,
            )
            return _to_schema(concurrent, is_idempotent_replay=True)
        raise AppError(
            "El fulfillment del pedido esta siendo procesado.",
            status_code=status.HTTP_409_CONFLICT,
            code="fulfillment_conflict",
        ) from exc
    except AppError as exc:
        db.rollback()
        if exc.code == "fulfillment_conflict":
            raise
        mapped_error = _map_operational_error(exc)
        _record_failed_attempt(
            db,
            actor,
            restaurant_id,
            order_id,
            mapped_error.code,
        )
        logger.warning(
            "order_fulfillment_failed restaurant_id=%s order_id=%s "
            "fulfillment_id=%s error_code=%s",
            restaurant_id,
            order_id,
            fulfillment_id,
            mapped_error.code,
        )
        raise mapped_error from exc
    except Exception as exc:
        db.rollback()
        _record_failed_attempt(
            db,
            actor,
            restaurant_id,
            order_id,
            "fulfillment_transaction_failed",
        )
        logger.exception(
            "order_fulfillment_failed restaurant_id=%s order_id=%s "
            "fulfillment_id=%s error_code=fulfillment_transaction_failed",
            restaurant_id,
            order_id,
            fulfillment_id,
        )
        raise AppError(
            "No se pudo registrar la operacion del pedido.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="fulfillment_transaction_failed",
        ) from exc

    completed = _require_fulfillment(db, restaurant_id, order_id)
    logger.info(
        "order_fulfillment_completed restaurant_id=%s order_id=%s "
        "fulfillment_id=%s",
        restaurant_id,
        order_id,
        completed.id,
    )
    return _to_schema(completed, is_idempotent_replay=False)


def get_order_fulfillment(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
) -> OrderFulfillmentRead:
    authorize_restaurant(db, actor, restaurant_id, Permission.ORDER_READ)
    _require_order_for_fulfillment(db, restaurant_id, order_id)
    fulfillment = _require_fulfillment(db, restaurant_id, order_id)
    return _to_schema(fulfillment, is_idempotent_replay=False)


def _validate_fulfillable(
    order: Order,
) -> tuple[list[KitchenTicketLine], list[KitchenTicketLine]]:
    if order.status != OrderStatus.SUBMITTED.value:
        raise AppError(
            "El pedido no esta en un estado cumplible.",
            status_code=status.HTTP_409_CONFLICT,
            code="order_not_fulfillable",
        )
    ticket = order.kitchen_ticket
    if ticket is None or ticket.status != KitchenStatus.SERVED.value:
        raise AppError(
            "La comanda debe estar servida antes del fulfillment.",
            status_code=status.HTTP_409_CONFLICT,
            code="kitchen_not_served",
        )
    served_lines = [
        line for line in ticket.lines
        if line.status == KitchenStatus.SERVED.value
    ]
    cancelled_lines = [
        line for line in ticket.lines
        if line.status == KitchenStatus.CANCELLED.value
    ]
    if len(served_lines) + len(cancelled_lines) != len(ticket.lines):
        raise AppError(
            "La comanda contiene lineas que aun no han sido servidas.",
            status_code=status.HTTP_409_CONFLICT,
            code="kitchen_not_served",
        )
    if not served_lines:
        raise AppError(
            "El pedido no contiene lineas servidas que se puedan cumplir.",
            status_code=status.HTTP_409_CONFLICT,
            code="fulfillment_no_served_lines",
        )
    for line in [*served_lines, *cancelled_lines]:
        order_line = line.order_line
        if (
            order_line is None
            or order_line.order_id != order.id
            or order_line.restaurant_id != order.restaurant_id
            or line.restaurant_id != order.restaurant_id
        ):
            raise AppError(
                "La trazabilidad de la comanda no es valida.",
                status_code=status.HTTP_409_CONFLICT,
                code="fulfillment_line_reference_invalid",
            )
    return served_lines, cancelled_lines


def _require_order_for_fulfillment(
    db: Session,
    restaurant_id: int,
    order_id: int,
) -> Order:
    order = db.scalar(
        select(Order)
        .options(
            selectinload(Order.lines),
            selectinload(Order.kitchen_ticket)
            .selectinload(KitchenTicket.lines)
            .selectinload(KitchenTicketLine.order_line),
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


def _fulfillment_statement():
    return (
        select(OrderFulfillment)
        .options(
            selectinload(OrderFulfillment.lines).selectinload(
                OrderFulfillmentLine.order_line
            )
        )
    )


def _get_fulfillment(
    db: Session,
    restaurant_id: int,
    order_id: int,
) -> OrderFulfillment | None:
    return db.scalar(
        _fulfillment_statement().where(
            OrderFulfillment.restaurant_id == restaurant_id,
            OrderFulfillment.order_id == order_id,
        )
    )


def _require_fulfillment(
    db: Session,
    restaurant_id: int,
    order_id: int,
) -> OrderFulfillment:
    fulfillment = _get_fulfillment(db, restaurant_id, order_id)
    if fulfillment is None:
        raise AppError(
            "El pedido aun no tiene un fulfillment registrado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="fulfillment_not_found",
        )
    return fulfillment


def _record_failed_attempt(
    db: Session,
    actor: User,
    restaurant_id: int,
    order_id: int,
    error_code: str,
) -> None:
    now = datetime.utcnow()
    fulfillment = _get_fulfillment(db, restaurant_id, order_id)
    if fulfillment is None:
        fulfillment = OrderFulfillment(
            restaurant_id=restaurant_id,
            order_id=order_id,
            status=FulfillmentStatus.FAILED.value,
            idempotency_key=_fulfillment_reference(
                restaurant_id,
                order_id,
            ),
            attempt_count=1,
            executed_by_user_id=actor.id,
            last_attempt_at=now,
            failed_at=now,
            error_code=error_code,
            created_at=now,
            updated_at=now,
        )
        db.add(fulfillment)
    elif fulfillment.status != FulfillmentStatus.COMPLETED.value:
        fulfillment.status = FulfillmentStatus.FAILED.value
        fulfillment.attempt_count += 1
        fulfillment.executed_by_user_id = actor.id
        fulfillment.last_attempt_at = now
        fulfillment.failed_at = now
        fulfillment.error_code = error_code
        fulfillment.updated_at = now
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "order_fulfillment_failure_record_failed restaurant_id=%s "
            "order_id=%s error_code=%s",
            restaurant_id,
            order_id,
            error_code,
        )


def _clear_stale_line_records(
    db: Session,
    fulfillment: OrderFulfillment,
) -> None:
    for line in list(fulfillment.lines):
        db.delete(line)
    db.flush()


def _map_operational_error(exc: AppError) -> AppError:
    mapped = _OPERATIONAL_ERROR_MAP.get(exc.code)
    if mapped is None:
        return AppError(
            "No se pudo registrar la operacion del pedido.",
            status_code=exc.status_code,
            code="fulfillment_transaction_failed",
        )
    code, message = mapped
    return AppError(
        message,
        status_code=status.HTTP_409_CONFLICT,
        code=code,
    )


def _to_schema(
    fulfillment: OrderFulfillment,
    *,
    is_idempotent_replay: bool,
) -> OrderFulfillmentRead:
    processed_lines: list[OrderFulfillmentLineRead] = []
    skipped_lines: list[OrderFulfillmentLineRead] = []
    for line in fulfillment.lines:
        payload = OrderFulfillmentLineRead(
            order_line_id=line.order_line_id,
            kitchen_ticket_line_id=line.kitchen_ticket_line_id,
            dish_id=line.dish_id,
            quantity=line.quantity,
            unit_price=line.order_line.unit_price,
            status=line.status,
            operational_reference=line.operational_reference,
            analytics_event_id=line.analytics_event_id,
            movement_ids=list(line.movement_ids),
        )
        if line.status == FulfillmentLineStatus.PROCESSED.value:
            processed_lines.append(payload)
        else:
            skipped_lines.append(payload)
    return OrderFulfillmentRead(
        order_id=fulfillment.order_id,
        fulfillment_id=fulfillment.id,
        status=fulfillment.status,
        executed_at=(
            fulfillment.completed_at
            or fulfillment.failed_at
            or fulfillment.last_attempt_at
        ),
        executed_by_user_id=fulfillment.executed_by_user_id,
        processed_lines=processed_lines,
        skipped_lines=skipped_lines,
        operational_reference=fulfillment.idempotency_key,
        is_idempotent_replay=is_idempotent_replay,
        error_code=fulfillment.error_code,
    )


def _fulfillment_reference(restaurant_id: int, order_id: int) -> str:
    return f"order-fulfillment:{restaurant_id}:{order_id}"


def _line_reference(
    restaurant_id: int,
    order_id: int,
    order_line_id: int,
) -> str:
    return (
        f"order-fulfillment:{restaurant_id}:{order_id}:"
        f"line:{order_line_id}"
    )

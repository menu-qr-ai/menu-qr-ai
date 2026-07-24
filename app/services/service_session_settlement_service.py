import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission
from app.core.dining import ServiceSessionStatus
from app.core.exceptions import AppError
from app.core.fulfillment import FulfillmentLineStatus, FulfillmentStatus
from app.core.money import (
    ZERO_MONEY,
    money_subtotal,
    normalize_money,
    sum_money,
)
from app.core.orders import OrderStatus
from app.core.settlement import SettlementStatus
from app.models import (
    Order,
    OrderFulfillment,
    OrderFulfillmentLine,
    ServiceSession,
    ServiceSessionSettlement,
    ServiceSessionSettlementLine,
    ServiceSessionSettlementOrder,
    User,
)
from app.schemas.settlement import (
    ServiceSessionSettlementLineRead,
    ServiceSessionSettlementOrderRead,
    ServiceSessionSettlementRead,
)
from app.services.access_service import authorize_restaurant
from app.services.service_session_service import (
    claim_open_service_session,
)


logger = logging.getLogger("app.service_session_settlement")


@dataclass(frozen=True)
class _LineSnapshot:
    order_line_id: int
    fulfillment_line_id: int
    dish_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


@dataclass(frozen=True)
class _OrderSnapshot:
    order_id: int
    frozen_total: Decimal
    lines: tuple[_LineSnapshot, ...]


def settle_service_session(
    db: Session,
    actor: User,
    restaurant_id: int,
    session_id: int,
) -> ServiceSessionSettlementRead:
    membership = authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.SETTLEMENT_CREATE,
    )
    existing = _get_settlement(db, restaurant_id, session_id)
    if existing is not None:
        return _replay(existing)

    try:
        service_session = claim_open_service_session(
            db,
            restaurant_id,
            session_id,
        )
    except AppError as exc:
        db.rollback()
        concurrent = _get_settlement(db, restaurant_id, session_id)
        if concurrent is not None:
            return _replay(concurrent)
        if exc.code == "service_session_not_open":
            raise AppError(
                "La sesion debe estar abierta para crear el settlement.",
                status_code=status.HTTP_409_CONFLICT,
                code="settlement_session_not_open",
            ) from exc
        raise

    now = datetime.utcnow()
    try:
        currency = _normalize_currency(membership.restaurant.currency)
    except AppError as exc:
        db.rollback()
        logger.warning(
            "service_session_settlement_failed restaurant_id=%s "
            "service_session_id=%s settlement_id=None error_code=%s",
            restaurant_id,
            session_id,
            exc.code,
        )
        raise
    settlement = ServiceSessionSettlement(
        restaurant_id=restaurant_id,
        service_session_id=service_session.id,
        status=SettlementStatus.FINALIZED.value,
        idempotency_key=_settlement_reference(
            restaurant_id,
            service_session.id,
        ),
        currency=currency,
        subtotal=ZERO_MONEY,
        total=ZERO_MONEY,
        created_by_user_id=actor.id,
        finalized_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(settlement)
    claim_established = False
    settlement_id: int | None = None
    try:
        db.flush()
        claim_established = True
        settlement_id = settlement.id
        logger.info(
            "service_session_settlement_started restaurant_id=%s "
            "service_session_id=%s settlement_id=%s",
            restaurant_id,
            session_id,
            settlement_id,
        )
        orders = _load_session_orders(
            db,
            restaurant_id,
            service_session.id,
        )
        order_snapshots = _build_order_snapshots(
            restaurant_id,
            service_session.id,
            orders,
        )
        total = normalize_money(
            sum_money(
                snapshot.frozen_total
                for snapshot in order_snapshots
            ),
            field_name="total del settlement",
        )
        settlement.subtotal = total
        settlement.total = total

        for order_snapshot in order_snapshots:
            settlement_order = ServiceSessionSettlementOrder(
                restaurant_id=restaurant_id,
                settlement_id=settlement.id,
                order_id=order_snapshot.order_id,
                frozen_total=order_snapshot.frozen_total,
                included_line_count=len(order_snapshot.lines),
                created_at=now,
            )
            db.add(settlement_order)
            db.flush()
            for line_snapshot in order_snapshot.lines:
                db.add(
                    ServiceSessionSettlementLine(
                        restaurant_id=restaurant_id,
                        settlement_order_id=settlement_order.id,
                        order_line_id=line_snapshot.order_line_id,
                        fulfillment_line_id=(
                            line_snapshot.fulfillment_line_id
                        ),
                        dish_name=line_snapshot.dish_name,
                        quantity=line_snapshot.quantity,
                        unit_price=line_snapshot.unit_price,
                        subtotal=line_snapshot.subtotal,
                        created_at=now,
                    )
                )

        _close_session_record(service_session, actor, now)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if not claim_established:
            concurrent = _get_settlement(
                db,
                restaurant_id,
                session_id,
            )
            if concurrent is not None:
                return _replay(concurrent)
            raise AppError(
                "El settlement de la sesion esta siendo procesado.",
                status_code=status.HTTP_409_CONFLICT,
                code="settlement_conflict",
            ) from exc
        _raise_transaction_failed(
            restaurant_id,
            session_id,
            settlement_id,
            exc,
        )
    except AppError as exc:
        db.rollback()
        logger.warning(
            "service_session_settlement_failed restaurant_id=%s "
            "service_session_id=%s settlement_id=%s error_code=%s",
            restaurant_id,
            session_id,
            settlement_id,
            exc.code,
        )
        raise
    except Exception as exc:
        db.rollback()
        _raise_transaction_failed(
            restaurant_id,
            session_id,
            settlement_id,
            exc,
        )

    completed = _require_settlement(db, restaurant_id, session_id)
    logger.info(
        "service_session_settlement_completed restaurant_id=%s "
        "service_session_id=%s settlement_id=%s total=%s currency=%s",
        restaurant_id,
        session_id,
        completed.id,
        completed.total,
        completed.currency,
    )
    return _to_schema(completed, is_idempotent_replay=False)


def get_service_session_settlement(
    db: Session,
    actor: User,
    restaurant_id: int,
    session_id: int,
) -> ServiceSessionSettlementRead:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.SETTLEMENT_READ,
    )
    settlement = _require_settlement(
        db,
        restaurant_id,
        session_id,
    )
    return _to_schema(settlement, is_idempotent_replay=False)


def _load_session_orders(
    db: Session,
    restaurant_id: int,
    session_id: int,
) -> list[Order]:
    return list(
        db.scalars(
            select(Order)
            .options(
                selectinload(Order.lines),
                selectinload(Order.fulfillment)
                .selectinload(OrderFulfillment.lines)
                .selectinload(OrderFulfillmentLine.order_line),
            )
            .where(
                Order.restaurant_id == restaurant_id,
                Order.service_session_id == session_id,
            )
            .order_by(Order.id)
        ).all()
    )


def _build_order_snapshots(
    restaurant_id: int,
    session_id: int,
    orders: list[Order],
) -> tuple[_OrderSnapshot, ...]:
    snapshots: list[_OrderSnapshot] = []
    for order in orders:
        if (
            order.restaurant_id != restaurant_id
            or order.service_session_id != session_id
        ):
            raise AppError(
                "La sesion contiene un pedido incompatible.",
                status_code=status.HTTP_409_CONFLICT,
                code="settlement_orders_pending",
            )
        if order.status == OrderStatus.CANCELLED.value:
            continue
        fulfillment = order.fulfillment
        if (
            fulfillment is not None
            and fulfillment.status
            != FulfillmentStatus.COMPLETED.value
        ):
            _raise_fulfillment_required()
        if order.status in (
            OrderStatus.DRAFT.value,
            OrderStatus.DRAFT_CUSTOMER.value,
            OrderStatus.SUBMITTED_CUSTOMER.value,
            OrderStatus.SUBMITTED.value,
        ):
            raise AppError(
                "La sesion contiene pedidos pendientes.",
                status_code=status.HTTP_409_CONFLICT,
                code="settlement_orders_pending",
            )
        if order.status != OrderStatus.COMPLETED.value:
            raise AppError(
                "La sesion contiene pedidos incompatibles.",
                status_code=status.HTTP_409_CONFLICT,
                code="settlement_orders_pending",
            )
        if fulfillment is None:
            _raise_fulfillment_required()
        snapshots.append(_build_order_snapshot(order, fulfillment))

    if not snapshots:
        raise AppError(
            "La sesion no contiene pedidos liquidables.",
            status_code=status.HTTP_409_CONFLICT,
            code="settlement_no_billable_orders",
        )
    return tuple(snapshots)


def _build_order_snapshot(
    order: Order,
    fulfillment: OrderFulfillment,
) -> _OrderSnapshot:
    if (
        fulfillment.restaurant_id != order.restaurant_id
        or fulfillment.order_id != order.id
    ):
        _raise_fulfillment_required()
    order_line_ids = {line.id for line in order.lines}
    fulfillment_line_ids = {
        line.order_line_id for line in fulfillment.lines
    }
    if order_line_ids != fulfillment_line_ids:
        _raise_fulfillment_required()

    line_snapshots: list[_LineSnapshot] = []
    for fulfillment_line in fulfillment.lines:
        if (
            fulfillment_line.status
            != FulfillmentLineStatus.PROCESSED.value
        ):
            continue
        order_line = fulfillment_line.order_line
        if (
            order_line is None
            or order_line.order_id != order.id
            or order_line.restaurant_id != order.restaurant_id
            or fulfillment_line.restaurant_id != order.restaurant_id
            or fulfillment_line.quantity != order_line.quantity
        ):
            _raise_fulfillment_required()
        unit_price = normalize_money(
            order_line.unit_price,
            field_name="precio congelado de linea",
        )
        line_snapshots.append(
            _LineSnapshot(
                order_line_id=order_line.id,
                fulfillment_line_id=fulfillment_line.id,
                dish_name=order_line.dish_name,
                quantity=order_line.quantity,
                unit_price=unit_price,
                subtotal=money_subtotal(
                    unit_price,
                    order_line.quantity,
                ),
            )
        )
    if not line_snapshots:
        _raise_fulfillment_required()
    frozen_total = normalize_money(
        sum_money(line.subtotal for line in line_snapshots),
        field_name="total congelado del pedido",
    )
    return _OrderSnapshot(
        order_id=order.id,
        frozen_total=frozen_total,
        lines=tuple(line_snapshots),
    )


def _settlement_statement():
    return select(ServiceSessionSettlement).options(
        selectinload(ServiceSessionSettlement.orders).selectinload(
            ServiceSessionSettlementOrder.lines
        )
    )


def _get_settlement(
    db: Session,
    restaurant_id: int,
    session_id: int,
) -> ServiceSessionSettlement | None:
    return db.scalar(
        _settlement_statement().where(
            ServiceSessionSettlement.restaurant_id == restaurant_id,
            ServiceSessionSettlement.service_session_id == session_id,
        )
    )


def _require_settlement(
    db: Session,
    restaurant_id: int,
    session_id: int,
) -> ServiceSessionSettlement:
    settlement = _get_settlement(db, restaurant_id, session_id)
    if settlement is None:
        raise AppError(
            "La sesion aun no tiene un settlement.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="settlement_not_found",
        )
    return settlement


def _close_session_record(
    service_session: ServiceSession,
    actor: User,
    now: datetime,
) -> None:
    if service_session.status != ServiceSessionStatus.OPEN.value:
        raise AppError(
            "La sesion debe estar abierta para crear el settlement.",
            status_code=status.HTTP_409_CONFLICT,
            code="settlement_session_not_open",
        )
    service_session.status = ServiceSessionStatus.CLOSED.value
    service_session.closed_at = now
    service_session.closed_by_user_id = actor.id
    service_session.updated_at = now


def _normalize_currency(value: str | None) -> str:
    currency = str(value or "").strip().upper()
    if not 3 <= len(currency) <= 8:
        raise AppError(
            "La moneda del restaurante no es valida.",
            status_code=status.HTTP_409_CONFLICT,
            code="settlement_currency_mismatch",
        )
    return currency


def _raise_fulfillment_required() -> None:
    raise AppError(
        "Todos los pedidos completados requieren fulfillment confirmado.",
        status_code=status.HTTP_409_CONFLICT,
        code="settlement_fulfillment_required",
    )


def _raise_transaction_failed(
    restaurant_id: int,
    session_id: int,
    settlement_id: int | None,
    exc: Exception,
) -> None:
    logger.exception(
        "service_session_settlement_failed restaurant_id=%s "
        "service_session_id=%s settlement_id=%s "
        "error_code=settlement_transaction_failed",
        restaurant_id,
        session_id,
        settlement_id,
        exc_info=exc,
    )
    raise AppError(
        "No se pudo finalizar el settlement de la sesion.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="settlement_transaction_failed",
    ) from exc


def _replay(
    settlement: ServiceSessionSettlement,
) -> ServiceSessionSettlementRead:
    logger.info(
        "service_session_settlement_replay restaurant_id=%s "
        "service_session_id=%s settlement_id=%s",
        settlement.restaurant_id,
        settlement.service_session_id,
        settlement.id,
    )
    return _to_schema(settlement, is_idempotent_replay=True)


def _to_schema(
    settlement: ServiceSessionSettlement,
    *,
    is_idempotent_replay: bool,
) -> ServiceSessionSettlementRead:
    return ServiceSessionSettlementRead(
        settlement_id=settlement.id,
        service_session_id=settlement.service_session_id,
        status=settlement.status,
        currency=settlement.currency,
        subtotal=settlement.subtotal,
        total=settlement.total,
        created_by_user_id=settlement.created_by_user_id,
        finalized_at=settlement.finalized_at,
        orders=[
            ServiceSessionSettlementOrderRead(
                order_id=settlement_order.order_id,
                frozen_total=settlement_order.frozen_total,
                included_line_count=(
                    settlement_order.included_line_count
                ),
                lines=[
                    ServiceSessionSettlementLineRead(
                        order_line_id=line.order_line_id,
                        fulfillment_line_id=line.fulfillment_line_id,
                        dish_name=line.dish_name,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                        subtotal=line.subtotal,
                    )
                    for line in settlement_order.lines
                ],
            )
            for settlement_order in settlement.orders
        ],
        is_idempotent_replay=is_idempotent_replay,
    )


def _settlement_reference(
    restaurant_id: int,
    session_id: int,
) -> str:
    return (
        f"service-session-settlement:{restaurant_id}:{session_id}"
    )

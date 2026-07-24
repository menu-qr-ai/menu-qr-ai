from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.exceptions import AppError
from app.models import InventoryItem, InventoryMovement
from app.schemas.inventory import InventoryMovementCreate, PurchaseIntakeCreate, PurchaseIntakeRead, PurchaseIntakeResult
from app.services.historical_valuation_service import valued_movement_payload_from_unit_cost
from app.services.inventory_service import create_inventory_movement_record
from app.services.inventory_valuation_service import WeightedAverageCostTrace, calculate_weighted_average_cost_trace
from app.services.restaurant_service import require_restaurant

PURCHASE_INTAKE_ORIGIN_TYPE = "purchase_intake"
DEFAULT_PURCHASE_INTAKE_LIMIT = 100
MAX_PURCHASE_INTAKE_LIMIT = 500


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
        return

    with db.begin():
        yield


def apply_weighted_average_purchase_cost(movement: InventoryMovement, weighted_average_cost: float) -> None:
    movement.inventory_item.cost = weighted_average_cost
    movement.inventory_item.updated_at = datetime.utcnow()


def _require_purchase_intake_item(db: Session, restaurant_id: int, item_id: int) -> InventoryItem:
    item = db.scalar(
        select(InventoryItem).where(
            InventoryItem.id == item_id,
            InventoryItem.restaurant_id == restaurant_id,
        )
    )
    if item is None:
        raise AppError(
            "Ingrediente no encontrado para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="inventory_item_not_found",
        )
    return item


def receive_purchase_intake(db: Session, payload: PurchaseIntakeCreate) -> PurchaseIntakeResult:
    received_at = payload.received_at or datetime.utcnow()

    with _transaction(db):
        require_restaurant(db, payload.restaurant_id)
        item = _require_purchase_intake_item(db, payload.restaurant_id, payload.inventory_item_id)
        weighted_average_trace: WeightedAverageCostTrace | None = None
        movement_payload = InventoryMovementCreate(
            restaurant_id=payload.restaurant_id,
            inventory_item_id=payload.inventory_item_id,
            movement_type="IN",
            quantity=payload.quantity,
            unit=payload.unit,
            reason=payload.reason,
            origin_type=payload.origin_type,
            origin_id=payload.origin_id,
            reference=payload.reference,
            note=payload.note,
            created_at=received_at,
        )
        if payload.unit_cost is not None:
            weighted_average_trace = calculate_weighted_average_cost_trace(
                item,
                payload.quantity,
                payload.unit_cost,
            )
            movement_payload = valued_movement_payload_from_unit_cost(movement_payload, payload.unit_cost)
            movement_payload = movement_payload.model_copy(
                update={
                    "wac_previous_stock": weighted_average_trace.previous_stock,
                    "wac_previous_unit_cost": weighted_average_trace.previous_unit_cost,
                    "wac_resulting_unit_cost": weighted_average_trace.resulting_unit_cost,
                }
            )

        movement = create_inventory_movement_record(
            db,
            movement_payload,
        )
        if payload.unit_cost is not None:
            assert weighted_average_trace is not None
            apply_weighted_average_purchase_cost(movement, weighted_average_trace.resulting_unit_cost)
        current_stock = movement.inventory_item.current_stock

    return PurchaseIntakeResult(
        restaurant_id=payload.restaurant_id,
        inventory_item_id=payload.inventory_item_id,
        quantity=payload.quantity,
        unit=movement.unit,
        unit_cost=movement.historical_unit_cost,
        historical_total_cost=movement.historical_total_cost,
        reason=movement.reason,
        received_at=movement.created_at,
        reference=movement.reference,
        movement_id=movement.id,
        current_stock=current_stock,
    )


def list_purchase_intakes(
    db: Session,
    *,
    restaurant_id: int | None = None,
    inventory_item_id: int | None = None,
    reference: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    is_valued: bool | None = None,
    limit: int = DEFAULT_PURCHASE_INTAKE_LIMIT,
) -> list[PurchaseIntakeRead]:
    if restaurant_id is not None:
        require_restaurant(db, restaurant_id)

    capped_limit = min(max(limit, 1), MAX_PURCHASE_INTAKE_LIMIT)
    statement = (
        select(InventoryMovement)
        .where(
            InventoryMovement.movement_type == "IN",
            InventoryMovement.origin_type == PURCHASE_INTAKE_ORIGIN_TYPE,
        )
        .options(selectinload(InventoryMovement.inventory_item))
    )
    if restaurant_id is not None:
        statement = statement.where(InventoryMovement.restaurant_id == restaurant_id)
    if inventory_item_id is not None:
        statement = statement.where(InventoryMovement.inventory_item_id == inventory_item_id)
    if reference is not None:
        statement = statement.where(InventoryMovement.reference == reference)
    if start_date is not None:
        statement = statement.where(InventoryMovement.created_at >= start_date)
    if end_date is not None:
        statement = statement.where(InventoryMovement.created_at <= end_date)
    if is_valued is not None:
        valued_clause = _valued_purchase_intake_clause()
        statement = statement.where(valued_clause if is_valued else ~valued_clause)

    statement = statement.order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc()).limit(capped_limit)
    return [_purchase_intake_read(movement) for movement in db.scalars(statement).all()]


def _purchase_intake_read(movement: InventoryMovement) -> PurchaseIntakeRead:
    is_valued = _is_valued_purchase_intake(movement)
    return PurchaseIntakeRead(
        id=movement.id,
        movement_id=movement.id,
        restaurant_id=movement.restaurant_id,
        inventory_item_id=movement.inventory_item_id,
        ingredient_name=movement.inventory_item.name if movement.inventory_item else None,
        quantity=movement.quantity,
        unit=movement.unit,
        reference=movement.reference,
        reason=movement.reason,
        received_at=movement.created_at,
        created_by=movement.created_by,
        purchase_unit_cost=movement.historical_unit_cost,
        purchase_total_cost=movement.historical_total_cost,
        previous_stock=movement.wac_previous_stock,
        previous_unit_cost=movement.wac_previous_unit_cost,
        resulting_unit_cost=movement.wac_resulting_unit_cost,
        is_valued=is_valued,
    )


def _is_valued_purchase_intake(movement: InventoryMovement) -> bool:
    if (
        movement.historical_unit_cost is None
        or movement.historical_total_cost is None
        or movement.wac_previous_stock is None
        or movement.wac_resulting_unit_cost is None
    ):
        return False
    return movement.wac_previous_stock == 0 or movement.wac_previous_unit_cost is not None


def _valued_purchase_intake_clause():
    return (
        InventoryMovement.historical_unit_cost.is_not(None)
        & InventoryMovement.historical_total_cost.is_not(None)
        & InventoryMovement.wac_previous_stock.is_not(None)
        & InventoryMovement.wac_resulting_unit_cost.is_not(None)
        & (
            (InventoryMovement.wac_previous_stock == 0)
            | InventoryMovement.wac_previous_unit_cost.is_not(None)
        )
    )

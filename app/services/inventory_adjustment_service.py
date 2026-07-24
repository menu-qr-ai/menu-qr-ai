from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InventoryItem, InventoryMovement
from app.schemas.inventory import (
    InventoryAdjustmentCreate,
    InventoryAdjustmentResult,
    InventoryMovementCreate,
    InventoryReconciliationItem,
    InventoryReconciliationResponse,
)
from app.services.inventory_service import create_inventory_movement_record, list_inventory_items
from app.services.restaurant_service import require_restaurant


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
        return

    with db.begin():
        yield


def _adjustment_movement_type(stock_difference: float) -> str:
    return "ADJUSTMENT_POSITIVE" if stock_difference > 0 else "ADJUSTMENT_NEGATIVE"


def record_inventory_adjustment(db: Session, payload: InventoryAdjustmentCreate) -> InventoryAdjustmentResult:
    adjusted_at = payload.adjusted_at or datetime.utcnow()
    movement_type = _adjustment_movement_type(payload.stock_difference)
    quantity = abs(payload.stock_difference)

    with _transaction(db):
        require_restaurant(db, payload.restaurant_id)
        movement = create_inventory_movement_record(
            db,
            InventoryMovementCreate(
                restaurant_id=payload.restaurant_id,
                inventory_item_id=payload.inventory_item_id,
                movement_type=movement_type,
                quantity=quantity,
                unit=payload.unit,
                reason=payload.reason,
                origin_type="inventory_adjustment",
                reference=payload.reference,
                created_by=payload.created_by,
                note=payload.note,
                created_at=adjusted_at,
            ),
        )
        current_stock = movement.inventory_item.current_stock

    return InventoryAdjustmentResult(
        restaurant_id=payload.restaurant_id,
        inventory_item_id=payload.inventory_item_id,
        stock_difference=payload.stock_difference,
        unit=movement.unit,
        reason=movement.reason,
        adjusted_at=movement.created_at,
        reference=movement.reference,
        movement_id=movement.id,
        movement_type=movement.movement_type,
        current_stock=current_stock,
    )


def _movement_delta(movement: InventoryMovement) -> float:
    if movement.movement_type in {"IN", "ADJUSTMENT", "ADJUSTMENT_POSITIVE", "PRODUCTION_OUTPUT"}:
        return movement.quantity
    if movement.movement_type in {"OUT", "WASTE", "ADJUSTMENT_NEGATIVE", "PRODUCTION_CONSUME"}:
        return -movement.quantity
    return 0


def _expected_stock_by_item(movements: list[InventoryMovement]) -> dict[int, float]:
    expected: dict[int, float] = defaultdict(float)
    for movement in movements:
        expected[movement.inventory_item_id] += _movement_delta(movement)
    return {item_id: round(value, 4) for item_id, value in expected.items()}


def get_inventory_reconciliation(db: Session, restaurant_id: int | None = None) -> InventoryReconciliationResponse:
    if restaurant_id is not None:
        require_restaurant(db, restaurant_id)

    items = list_inventory_items(db, restaurant_id=restaurant_id)
    item_ids = [item.id for item in items if item.id is not None]
    movements: list[InventoryMovement] = []
    if item_ids:
        statement = select(InventoryMovement).where(InventoryMovement.inventory_item_id.in_(item_ids))
        if restaurant_id is not None:
            statement = statement.where(InventoryMovement.restaurant_id == restaurant_id)
        movements = list(db.scalars(statement).all())

    expected_by_item = _expected_stock_by_item(movements)
    reconciliation_items = [_reconciliation_item(item, expected_by_item.get(item.id, 0)) for item in items]

    return InventoryReconciliationResponse(
        restaurant_id=restaurant_id,
        total_items=len(reconciliation_items),
        discrepant_items=sum(1 for item in reconciliation_items if item.status == "discrepant"),
        items=reconciliation_items,
    )


def _reconciliation_item(item: InventoryItem, expected_stock: float) -> InventoryReconciliationItem:
    operational_stock = round(item.current_stock, 4)
    expected = round(expected_stock, 4)
    difference = round(operational_stock - expected, 4)
    return InventoryReconciliationItem(
        restaurant_id=item.restaurant_id,
        inventory_item_id=item.id,
        ingredient_name=item.name,
        unit=item.unit,
        operational_stock=operational_stock,
        expected_stock=expected,
        difference=difference,
        status="ok" if difference == 0 else "discrepant",
    )

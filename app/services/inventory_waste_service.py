from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InventoryMovement
from app.schemas.inventory import InventoryMovementCreate, InventoryWasteLossCreate, InventoryWasteLossRead
from app.services.historical_valuation_service import valued_inventory_movement_payload
from app.services.inventory_service import create_inventory_movement_record
from app.services.restaurant_service import require_restaurant


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
        return

    with db.begin():
        yield


def record_inventory_waste_loss(db: Session, payload: InventoryWasteLossCreate) -> InventoryWasteLossRead:
    occurred_at = payload.occurred_at or datetime.utcnow()

    with _transaction(db):
        require_restaurant(db, payload.restaurant_id)
        movement = create_inventory_movement_record(
            db,
            valued_inventory_movement_payload(
                db,
                InventoryMovementCreate(
                    restaurant_id=payload.restaurant_id,
                    inventory_item_id=payload.inventory_item_id,
                    movement_type="WASTE",
                    quantity=payload.quantity,
                    unit=payload.unit,
                    reason=payload.reason,
                    origin_type="inventory_waste_loss",
                    reference=payload.reference,
                    loss_category=payload.loss_category,
                    created_by=payload.created_by,
                    note=payload.note,
                    created_at=occurred_at,
                ),
                error_code="waste_cost_missing",
            ),
        )
        current_stock = movement.inventory_item.current_stock

    return _waste_loss_read(movement, current_stock)


def list_inventory_waste_losses(db: Session, restaurant_id: int | None = None) -> list[InventoryWasteLossRead]:
    if restaurant_id is not None:
        require_restaurant(db, restaurant_id)
    statement = select(InventoryMovement).where(InventoryMovement.movement_type == "WASTE").order_by(InventoryMovement.created_at.desc())
    if restaurant_id is not None:
        statement = statement.where(InventoryMovement.restaurant_id == restaurant_id)
    return [_waste_loss_read(movement, movement.inventory_item.current_stock) for movement in db.scalars(statement).all()]


def _waste_loss_read(movement: InventoryMovement, current_stock: float) -> InventoryWasteLossRead:
    return InventoryWasteLossRead(
        restaurant_id=movement.restaurant_id,
        inventory_item_id=movement.inventory_item_id,
        quantity=movement.quantity,
        unit=movement.unit,
        reason=movement.reason,
        loss_category=movement.loss_category or "other",
        occurred_at=movement.created_at,
        reference=movement.reference,
        created_by=movement.created_by,
        movement_id=movement.id,
        current_stock=current_stock,
        historical_unit_cost=movement.historical_unit_cost or 0,
        historical_total_cost=movement.historical_total_cost or 0,
    )

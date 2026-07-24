from contextlib import contextmanager
from datetime import datetime
from typing import Iterator
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InventoryMovement
from app.schemas.inventory import (
    InventoryMovementCreate,
    InventoryProductionCreate,
    InventoryProductionRead,
    ProducedIngredientConsumption,
)
from app.services.inventory_service import create_inventory_movement_record
from app.services.historical_valuation_service import money, require_recipe_costs_available, value_recipe_consumption
from app.services.restaurant_service import require_restaurant
from app.services.technical_recipe_service import require_recipe_ingredient, require_recipe_items


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
        return

    with db.begin():
        yield


def process_inventory_production(db: Session, payload: InventoryProductionCreate) -> InventoryProductionRead:
    produced_at = payload.produced_at or datetime.utcnow()
    origin_id = f"production:dish:{payload.dish_id}:{uuid4()}"
    consumed_ingredients: list[ProducedIngredientConsumption] = []

    with _transaction(db):
        require_restaurant(db, payload.restaurant_id)
        produced_item = require_recipe_ingredient(db, payload.restaurant_id, payload.produced_inventory_item_id)
        recipe = require_recipe_items(db, payload.restaurant_id, payload.dish_id)
        require_recipe_costs_available(recipe, error_code="production_cost_missing")

        historical_total_cost = 0.0
        for ingredient in recipe:
            consumed_quantity, historical_unit_cost, historical_line_cost = value_recipe_consumption(
                ingredient,
                payload.quantity,
                error_code="production_cost_missing",
            )
            historical_total_cost = money(historical_total_cost + historical_line_cost)
            movement = create_inventory_movement_record(
                db,
                InventoryMovementCreate(
                    restaurant_id=payload.restaurant_id,
                    inventory_item_id=ingredient.inventory_item_id,
                    movement_type="PRODUCTION_CONSUME",
                    quantity=consumed_quantity,
                    unit=ingredient.unit,
                    historical_unit_cost=historical_unit_cost,
                    historical_total_cost=historical_line_cost,
                    reason="production_consumption",
                    origin_type="inventory_production",
                    origin_id=origin_id,
                    reference=payload.reference,
                    created_by=payload.created_by,
                    note=payload.note,
                    created_at=produced_at,
                ),
            )
            consumed_ingredients.append(
                ProducedIngredientConsumption(
                    inventory_item_id=ingredient.inventory_item_id,
                    name=ingredient.inventory_item.name,
                    quantity=consumed_quantity,
                    unit=ingredient.unit,
                    movement_id=movement.id,
                    historical_unit_cost=historical_unit_cost,
                    historical_total_cost=historical_line_cost,
                )
            )

        historical_output_unit_cost = money(historical_total_cost / payload.quantity)
        output_movement = create_inventory_movement_record(
            db,
            InventoryMovementCreate(
                restaurant_id=payload.restaurant_id,
                inventory_item_id=payload.produced_inventory_item_id,
                movement_type="PRODUCTION_OUTPUT",
                quantity=payload.quantity,
                unit=payload.unit or produced_item.unit,
                historical_unit_cost=historical_output_unit_cost,
                historical_total_cost=historical_total_cost,
                reason="production_output",
                origin_type="inventory_production",
                origin_id=origin_id,
                reference=payload.reference,
                created_by=payload.created_by,
                note=payload.note,
                created_at=produced_at,
            ),
        )
        current_stock = output_movement.inventory_item.current_stock

    return InventoryProductionRead(
        restaurant_id=payload.restaurant_id,
        dish_id=payload.dish_id,
        produced_inventory_item_id=payload.produced_inventory_item_id,
        produced_item_name=produced_item.name,
        quantity=payload.quantity,
        unit=output_movement.unit,
        produced_at=output_movement.created_at,
        reference=output_movement.reference,
        created_by=output_movement.created_by,
        origin_id=origin_id,
        output_movement_id=output_movement.id,
        consumed_ingredients=consumed_ingredients,
        current_stock=current_stock,
        historical_unit_cost=output_movement.historical_unit_cost or 0,
        historical_total_cost=output_movement.historical_total_cost or 0,
    )


def list_inventory_productions(db: Session, restaurant_id: int | None = None) -> list[InventoryProductionRead]:
    if restaurant_id is not None:
        require_restaurant(db, restaurant_id)
    statement = (
        select(InventoryMovement)
        .where(InventoryMovement.movement_type == "PRODUCTION_OUTPUT")
        .order_by(InventoryMovement.created_at.desc())
    )
    if restaurant_id is not None:
        statement = statement.where(InventoryMovement.restaurant_id == restaurant_id)
    return [_production_read_from_output(db, movement) for movement in db.scalars(statement).all()]


def _production_read_from_output(db: Session, output_movement: InventoryMovement) -> InventoryProductionRead:
    consumption_statement = (
        select(InventoryMovement)
        .where(
            InventoryMovement.restaurant_id == output_movement.restaurant_id,
            InventoryMovement.origin_type == "inventory_production",
            InventoryMovement.origin_id == output_movement.origin_id,
            InventoryMovement.movement_type == "PRODUCTION_CONSUME",
        )
        .order_by(InventoryMovement.id)
    )
    consumptions = list(db.scalars(consumption_statement).all())
    return InventoryProductionRead(
        restaurant_id=output_movement.restaurant_id,
        dish_id=_dish_id_from_origin_id(output_movement.origin_id),
        produced_inventory_item_id=output_movement.inventory_item_id,
        produced_item_name=output_movement.inventory_item.name,
        quantity=output_movement.quantity,
        unit=output_movement.unit,
        produced_at=output_movement.created_at,
        reference=output_movement.reference,
        created_by=output_movement.created_by,
        origin_id=output_movement.origin_id or "",
        output_movement_id=output_movement.id,
        consumed_ingredients=[
            ProducedIngredientConsumption(
                inventory_item_id=movement.inventory_item_id,
                name=movement.inventory_item.name,
                quantity=movement.quantity,
                unit=movement.unit,
                movement_id=movement.id,
                historical_unit_cost=movement.historical_unit_cost or 0,
                historical_total_cost=movement.historical_total_cost or 0,
            )
            for movement in consumptions
        ],
        current_stock=output_movement.inventory_item.current_stock,
        historical_unit_cost=output_movement.historical_unit_cost or 0,
        historical_total_cost=output_movement.historical_total_cost or 0,
    )


def _dish_id_from_origin_id(origin_id: str | None) -> int:
    if not origin_id:
        return 0
    parts = origin_id.split(":")
    if len(parts) >= 4 and parts[0] == "production" and parts[1] == "dish":
        try:
            return int(parts[2])
        except ValueError:
            return 0
    return 0

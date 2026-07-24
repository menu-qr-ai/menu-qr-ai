from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.models import Dish
from app.schemas.analytics import AnalyticsEventCreate
from app.schemas.inventory import InventoryMovementCreate
from app.schemas.operational_transaction import (
    ConsumedIngredient,
    SaleTransactionCreate,
    SaleTransactionResult,
)
from app.services.analytics_event_service import create_event_record
from app.services.historical_valuation_service import require_recipe_costs_available, value_recipe_consumption
from app.services.inventory_service import create_inventory_movement_record
from app.services.prediction_service import get_prediction_overview
from app.services.restaurant_service import require_restaurant
from app.services.technical_recipe_service import require_recipe_items


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    if db.in_transaction():
        with db.begin_nested():
            yield
        return

    with db.begin():
        yield


def _require_dish(db: Session, restaurant_id: int, dish_id: int) -> Dish:
    dish = db.scalar(select(Dish).where(Dish.id == dish_id, Dish.restaurant_id == restaurant_id))
    if dish is None:
        raise AppError(
            "Plato no encontrado para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="dish_not_found",
        )
    return dish


def process_sale_transaction(db: Session, payload: SaleTransactionCreate) -> SaleTransactionResult:
    occurred_at = payload.occurred_at or datetime.utcnow()
    consumed_ingredients: list[ConsumedIngredient] = []
    movement_ids: list[int] = []

    with _transaction(db):
        require_restaurant(db, payload.restaurant_id)
        dish = _require_dish(db, payload.restaurant_id, payload.dish_id)
        recipe = require_recipe_items(db, payload.restaurant_id, payload.dish_id)
        require_recipe_costs_available(recipe, error_code="sale_cost_missing")

        operational_reference = (
            payload.reference
            or f"{payload.source}:dish:{payload.dish_id}"
        )
        for ingredient in recipe:
            consumed_quantity, historical_unit_cost, historical_line_cost = value_recipe_consumption(
                ingredient,
                payload.quantity,
                error_code="sale_cost_missing",
            )
            movement = create_inventory_movement_record(
                db,
                InventoryMovementCreate(
                    restaurant_id=payload.restaurant_id,
                    inventory_item_id=ingredient.inventory_item_id,
                    movement_type="OUT",
                    quantity=consumed_quantity,
                    unit=ingredient.unit,
                    historical_unit_cost=historical_unit_cost,
                    historical_total_cost=historical_line_cost,
                    reason="sale",
                    origin_type="sale",
                    origin_id=operational_reference,
                    note=f"sale:{payload.source}:dish:{payload.dish_id}",
                ),
            )
            movement_ids.append(movement.id)
            consumed_ingredients.append(
                ConsumedIngredient(
                    inventory_item_id=ingredient.inventory_item_id,
                    name=ingredient.inventory_item.name,
                    unit=ingredient.unit,
                    quantity=consumed_quantity,
                    movement_id=movement.id,
                    historical_unit_cost=historical_unit_cost,
                    historical_total_cost=historical_line_cost,
                )
            )

        analytics_event = create_event_record(
            db,
            AnalyticsEventCreate(
                restaurant_id=payload.restaurant_id,
                event_type="sale_processed",
                dish_id=payload.dish_id,
                metadata={
                    "quantity": payload.quantity,
                    "source": payload.source,
                    "reference": operational_reference,
                    "occurred_at": occurred_at.isoformat(),
                    "movement_ids": movement_ids,
                },
            ),
        )

        prediction = get_prediction_overview(db, restaurant_id=payload.restaurant_id, range_value="all")

    return SaleTransactionResult(
        restaurant_id=payload.restaurant_id,
        dish_id=payload.dish_id,
        dish_name=dish.name,
        quantity=payload.quantity,
        occurred_at=occurred_at,
        source=payload.source,
        consumed_ingredients=consumed_ingredients,
        movement_ids=movement_ids,
        analytics_event_id=analytics_event.id,
        prediction=prediction,
    )

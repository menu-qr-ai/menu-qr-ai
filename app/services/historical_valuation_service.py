from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.models import DishIngredient, InventoryItem
from app.schemas.inventory import InventoryMovementCreate


def money(value: float) -> float:
    return round(value, 2)


def require_inventory_item_cost(item: InventoryItem, error_code: str = "historical_cost_missing") -> float:
    if item.cost is None:
        raise AppError(
            "La operacion requiere coste unitario historico para el ingrediente.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code=error_code,
        )
    return float(item.cost)


def valued_movement_payload(
    payload: InventoryMovementCreate,
    item: InventoryItem,
    *,
    error_code: str = "historical_cost_missing",
) -> InventoryMovementCreate:
    unit_cost = require_inventory_item_cost(item, error_code=error_code)
    return payload.model_copy(
        update={
            "historical_unit_cost": unit_cost,
            "historical_total_cost": money(payload.quantity * unit_cost),
        }
    )


def valued_movement_payload_from_unit_cost(
    payload: InventoryMovementCreate,
    unit_cost: float,
) -> InventoryMovementCreate:
    return payload.model_copy(
        update={
            "historical_unit_cost": unit_cost,
            "historical_total_cost": money(payload.quantity * unit_cost),
        }
    )


def require_recipe_costs_available(recipe: list[DishIngredient], error_code: str = "historical_cost_missing") -> None:
    for link in recipe:
        require_inventory_item_cost(link.inventory_item, error_code=error_code)


def value_recipe_consumption(
    link: DishIngredient,
    quantity_multiplier: float,
    *,
    error_code: str = "historical_cost_missing",
) -> tuple[float, float, float]:
    quantity = link.quantity * quantity_multiplier
    unit_cost = require_inventory_item_cost(link.inventory_item, error_code=error_code)
    return quantity, unit_cost, money(quantity * unit_cost)


def valued_inventory_movement_payload(
    db: Session,
    payload: InventoryMovementCreate,
    *,
    error_code: str = "historical_cost_missing",
) -> InventoryMovementCreate:
    item = db.get(InventoryItem, payload.inventory_item_id)
    if item is None or item.restaurant_id != payload.restaurant_id:
        return payload
    return valued_movement_payload(payload, item, error_code=error_code)

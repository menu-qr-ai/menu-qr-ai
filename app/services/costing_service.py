from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.exceptions import AppError
from app.core.money import (
    ZERO_MONEY,
    decimal_from_value,
    normalize_money,
    quantize_money,
    sum_money,
)
from app.models import Dish, DishIngredient
from app.schemas.costing import DishCosting, DishCostingList, IngredientCostLine
from app.services.restaurant_service import require_restaurant


def _require_dish(db: Session, restaurant_id: int, dish_id: int) -> Dish:
    dish = db.scalar(select(Dish).where(Dish.id == dish_id, Dish.restaurant_id == restaurant_id))
    if dish is None:
        raise AppError(
            "Plato no encontrado para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="dish_not_found",
        )
    return dish


def _load_recipe(db: Session, restaurant_id: int, dish_id: int) -> list[DishIngredient]:
    return list(
        db.scalars(
            select(DishIngredient)
            .where(DishIngredient.restaurant_id == restaurant_id, DishIngredient.dish_id == dish_id)
            .options(selectinload(DishIngredient.inventory_item))
            .order_by(DishIngredient.id)
        ).all()
    )


def _margin_percentage(
    sale_price: Decimal,
    gross_margin: Decimal,
) -> float | None:
    if sale_price <= ZERO_MONEY:
        return None
    percentage = ((gross_margin / sale_price) * Decimal(100)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    return float(percentage)


def _percentage(part: Decimal, whole: Decimal) -> float | None:
    if whole <= ZERO_MONEY:
        return None
    return float(((part / whole) * Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _ingredient_line(link: DishIngredient) -> IngredientCostLine:
    item = link.inventory_item
    unit_cost = decimal_from_value(item.cost or 0, field_name="coste unitario")
    # Cost what leaves the store room, not what reaches the plate.
    gross_quantity = decimal_from_value(link.stock_quantity, field_name="cantidad")
    line_cost = quantize_money(gross_quantity * unit_cost)
    return IngredientCostLine(
        ingredient_id=item.id,
        ingredient_name=item.name,
        quantity=link.quantity,
        unit=link.unit,
        unit_cost=float(unit_cost),
        line_cost=float(line_cost),
        missing_cost=item.cost is None,
        recipe_line_id=link.id,
        yield_percentage=link.yield_percentage or 100,
        gross_quantity=round(link.stock_quantity, 4),
        ingredient_unit=item.unit,
        unit_mismatch=link.unit != item.unit,
    )


def get_dish_costing(db: Session, restaurant_id: int, dish_id: int) -> DishCosting:
    restaurant = require_restaurant(db, restaurant_id)
    dish = _require_dish(db, restaurant_id, dish_id)
    recipe = _load_recipe(db, restaurant_id, dish_id)
    breakdown = [_ingredient_line(link) for link in recipe]
    total_cost = sum_money(
        decimal_from_value(line.line_cost, field_name="coste de linea")
        for line in breakdown
    )
    sale_price = normalize_money(
        dish.price or ZERO_MONEY,
        field_name="precio de venta",
    )
    gross_margin = quantize_money(sale_price - total_cost)
    vat = decimal_from_value(restaurant.vat_percentage or 0, field_name="IVA")
    price_without_vat = quantize_money(sale_price / (Decimal(1) + vat / Decimal(100)))
    net_margin = quantize_money(price_without_vat - total_cost)
    return DishCosting(
        restaurant_id=restaurant_id,
        dish_id=dish.id,
        dish_name=dish.name,
        sale_price=float(sale_price),
        total_cost=float(total_cost),
        gross_margin=float(gross_margin),
        margin_percentage=_margin_percentage(sale_price, gross_margin),
        has_recipe=bool(recipe),
        missing_costs=any(line.missing_cost for line in breakdown),
        ingredients_breakdown=breakdown,
        vat_percentage=float(vat),
        price_without_vat=float(price_without_vat),
        food_cost_percentage=_percentage(total_cost, price_without_vat),
        net_margin=float(net_margin),
        net_margin_percentage=_percentage(net_margin, price_without_vat),
        is_active=dish.is_active,
        category_id=dish.category_id,
    )


def list_dish_costings(db: Session, restaurant_id: int) -> DishCostingList:
    require_restaurant(db, restaurant_id)
    dish_ids = db.scalars(
        select(Dish.id).where(Dish.restaurant_id == restaurant_id).order_by(Dish.name, Dish.id)
    ).all()
    return DishCostingList(
        restaurant_id=restaurant_id,
        dishes=[get_dish_costing(db, restaurant_id, dish_id) for dish_id in dish_ids],
    )


def require_recipe_costs_available(recipe: list[DishIngredient]) -> None:
    missing = [link.inventory_item.name for link in recipe if link.inventory_item.cost is None]
    if missing:
        raise AppError(
            "La produccion requiere costes unitarios en todos los ingredientes.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="production_cost_missing",
        )

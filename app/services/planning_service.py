from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.exceptions import AppError
from app.models import DishIngredient, InventoryItem, InventoryMovement
from app.schemas.planning import (
    DishStockImpact,
    InventoryPlanningItem,
    InventoryPlanningResponse,
    InventoryPlanningSummary,
)
from app.services.inventory_service import list_inventory_items
from app.services.prediction_service import get_inventory_forecast
from app.services.restaurant_service import require_restaurant


PLANNING_RANGES = {"7d", "30d", "90d", "all"}
DEFAULT_PLANNING_RANGE = "30d"
CONSUMPTION_MOVEMENT_TYPES = {"OUT", "WASTE", "PRODUCTION_CONSUME"}


def normalize_planning_range(range_value: str | None) -> str:
    normalized = (range_value or DEFAULT_PLANNING_RANGE).strip().lower()
    return normalized if normalized in PLANNING_RANGES else DEFAULT_PLANNING_RANGE


def _range_start(range_value: str, now: datetime) -> datetime | None:
    if range_value == "7d":
        return now - timedelta(days=7)
    if range_value == "30d":
        return now - timedelta(days=30)
    if range_value == "90d":
        return now - timedelta(days=90)
    return None


def _range_days(range_value: str, movements: list[InventoryMovement]) -> int:
    if range_value == "7d":
        return 7
    if range_value == "30d":
        return 30
    if range_value == "90d":
        return 90
    if not movements:
        return 0
    first_day = min(movement.created_at for movement in movements).date()
    return max((datetime.utcnow().date() - first_day).days + 1, 1)


def _load_consumption_movements(
    db: Session,
    restaurant_id: int | None,
    item_ids: list[int],
    range_value: str,
) -> list[InventoryMovement]:
    if not item_ids:
        return []
    statement = (
        select(InventoryMovement)
        .where(
            InventoryMovement.inventory_item_id.in_(item_ids),
            InventoryMovement.movement_type.in_(CONSUMPTION_MOVEMENT_TYPES),
        )
        .order_by(InventoryMovement.created_at)
    )
    if restaurant_id is not None:
        statement = statement.where(InventoryMovement.restaurant_id == restaurant_id)
    start = _range_start(range_value, datetime.utcnow())
    if start is not None:
        statement = statement.where(InventoryMovement.created_at >= start)
    return list(db.scalars(statement).all())


def _load_recipe_links(db: Session, restaurant_id: int | None, item_ids: list[int]) -> list[DishIngredient]:
    if not item_ids:
        return []
    statement = (
        select(DishIngredient)
        .where(DishIngredient.inventory_item_id.in_(item_ids))
        .options(selectinload(DishIngredient.dish))
        .order_by(DishIngredient.inventory_item_id, DishIngredient.dish_id)
    )
    if restaurant_id is not None:
        statement = statement.where(DishIngredient.restaurant_id == restaurant_id)
    return list(db.scalars(statement).all())


def _consumption_by_item(
    movements: list[InventoryMovement],
    range_value: str,
) -> dict[int, tuple[float, float | None]]:
    movements_by_item: dict[int, list[InventoryMovement]] = defaultdict(list)
    for movement in movements:
        movements_by_item[movement.inventory_item_id].append(movement)

    consumption: dict[int, tuple[float, float | None]] = {}
    for item_id, item_movements in movements_by_item.items():
        total = sum(movement.quantity for movement in item_movements)
        days = _range_days(range_value, item_movements)
        average = round(total / days, 4) if days > 0 else None
        consumption[item_id] = (round(total, 4), average)
    return consumption


def _status(item: InventoryItem, days_remaining: float | None) -> str:
    if item.current_stock <= 0:
        return "out_of_stock"
    if item.minimum_stock and item.current_stock <= item.minimum_stock:
        return "critical"
    if days_remaining is not None and days_remaining <= 2:
        return "critical"
    if item.ideal_stock and item.current_stock < item.ideal_stock:
        return "low"
    if days_remaining is not None and days_remaining <= 5:
        return "low"
    return "ok"


def _priority(status: str, affected_count: int, demand_pressure: int) -> str:
    if status == "out_of_stock":
        return "urgent"
    if status == "critical":
        return "urgent" if affected_count or demand_pressure else "high"
    if status == "low":
        return "high" if affected_count or demand_pressure else "medium"
    return "monitor" if demand_pressure else "low"


def _impact_lines(item: InventoryItem, links: list[DishIngredient]) -> list[DishStockImpact]:
    impacts: list[DishStockImpact] = []
    for link in links:
        servings = round(item.current_stock / link.quantity, 2) if link.quantity > 0 else None
        impacts.append(
            DishStockImpact(
                dish_id=link.dish_id,
                dish_name=link.dish.name if link.dish else f"Plato #{link.dish_id}",
                required_quantity=link.quantity,
                unit=link.unit,
                estimated_servings_remaining=servings,
                is_blocked=item.current_stock < link.quantity,
            )
        )
    return impacts


def _require_planning_item(db: Session, restaurant_id: int, item_id: int) -> InventoryItem:
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


def get_inventory_planning(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> InventoryPlanningResponse:
    normalized_range = normalize_planning_range(range_value)
    if restaurant_id is not None:
        require_restaurant(db, restaurant_id)

    items = list_inventory_items(db, restaurant_id=restaurant_id, active_only=True)
    item_ids = [item.id for item in items if item.id is not None]
    movements = _load_consumption_movements(db, restaurant_id, item_ids, normalized_range)
    consumption = _consumption_by_item(movements, normalized_range)
    links = _load_recipe_links(db, restaurant_id, item_ids)
    links_by_item: dict[int, list[DishIngredient]] = defaultdict(list)
    for link in links:
        links_by_item[link.inventory_item_id].append(link)

    forecast_by_item = {
        item.inventory_item_id: item.demand_pressure
        for item in get_inventory_forecast(db, restaurant_id=restaurant_id, range_value=normalized_range)
    }

    planning_items: list[InventoryPlanningItem] = []
    for item in items:
        total_consumption, average_daily_consumption = consumption.get(item.id, (0, None))
        days_remaining = (
            round(item.current_stock / average_daily_consumption, 2)
            if average_daily_consumption and average_daily_consumption > 0
            else None
        )
        impacted_dishes = _impact_lines(item, links_by_item.get(item.id, []))
        item_status = _status(item, days_remaining)
        demand_pressure = forecast_by_item.get(item.id, 0)
        planning_items.append(
            InventoryPlanningItem(
                restaurant_id=item.restaurant_id,
                inventory_item_id=item.id,
                name=item.name,
                unit=item.unit,
                current_stock=item.current_stock,
                minimum_stock=item.minimum_stock,
                ideal_stock=item.ideal_stock,
                historical_consumption=total_consumption,
                average_daily_consumption=average_daily_consumption,
                estimated_days_remaining=days_remaining,
                status=item_status,
                replenishment_priority=_priority(item_status, len(impacted_dishes), demand_pressure),
                has_consumption_data=average_daily_consumption is not None,
                affected_dishes_count=len(impacted_dishes),
                blocked_dishes_count=sum(1 for dish in impacted_dishes if dish.is_blocked),
                demand_pressure=demand_pressure,
                impacted_dishes=impacted_dishes,
            )
        )

    planning_items = sorted(
        planning_items,
        key=lambda item: (
            {"urgent": 0, "high": 1, "medium": 2, "monitor": 3, "low": 4}.get(item.replenishment_priority, 5),
            item.estimated_days_remaining if item.estimated_days_remaining is not None else 9999,
            item.name,
        ),
    )
    summary = _summary(restaurant_id, normalized_range, planning_items)
    return InventoryPlanningResponse(
        restaurant_id=restaurant_id,
        range=normalized_range,
        summary=summary,
        items=planning_items,
    )


def _summary(
    restaurant_id: int | None,
    range_value: str,
    items: list[InventoryPlanningItem],
) -> InventoryPlanningSummary:
    return InventoryPlanningSummary(
        restaurant_id=restaurant_id,
        range=range_value,
        total_items=len(items),
        out_of_stock_items=sum(1 for item in items if item.status == "out_of_stock"),
        critical_items=sum(1 for item in items if item.status == "critical"),
        low_items=sum(1 for item in items if item.status == "low"),
        ok_items=sum(1 for item in items if item.status == "ok"),
        items_without_consumption_data=sum(1 for item in items if not item.has_consumption_data),
        blocked_dishes_count=sum(item.blocked_dishes_count for item in items),
    )


def get_inventory_planning_item(
    db: Session,
    restaurant_id: int,
    item_id: int,
    range_value: str | None = None,
) -> InventoryPlanningItem:
    _require_planning_item(db, restaurant_id, item_id)
    planning = get_inventory_planning(db, restaurant_id=restaurant_id, range_value=range_value)
    for item in planning.items:
        if item.inventory_item_id == item_id:
            return item
    raise AppError(
        "Ingrediente no encontrado para este restaurante.",
        status_code=status.HTTP_404_NOT_FOUND,
        code="inventory_item_not_found",
    )


def list_critical_inventory_planning(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> list[InventoryPlanningItem]:
    planning = get_inventory_planning(db, restaurant_id=restaurant_id, range_value=range_value)
    return [
        item
        for item in planning.items
        if item.status in {"out_of_stock", "critical"} or item.replenishment_priority in {"urgent", "high"}
    ]

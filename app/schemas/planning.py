from app.schemas.common import ORMModel


class DishStockImpact(ORMModel):
    dish_id: int
    dish_name: str
    required_quantity: float
    unit: str
    estimated_servings_remaining: float | None = None
    is_blocked: bool = False


class InventoryPlanningItem(ORMModel):
    restaurant_id: int
    inventory_item_id: int
    name: str
    unit: str
    current_stock: float
    minimum_stock: float
    ideal_stock: float
    historical_consumption: float
    average_daily_consumption: float | None = None
    estimated_days_remaining: float | None = None
    status: str
    replenishment_priority: str
    has_consumption_data: bool
    affected_dishes_count: int
    blocked_dishes_count: int
    demand_pressure: int = 0
    impacted_dishes: list[DishStockImpact]


class InventoryPlanningSummary(ORMModel):
    restaurant_id: int | None = None
    range: str
    total_items: int
    out_of_stock_items: int
    critical_items: int
    low_items: int
    ok_items: int
    items_without_consumption_data: int
    blocked_dishes_count: int


class InventoryPlanningResponse(ORMModel):
    restaurant_id: int | None = None
    range: str
    summary: InventoryPlanningSummary
    items: list[InventoryPlanningItem]

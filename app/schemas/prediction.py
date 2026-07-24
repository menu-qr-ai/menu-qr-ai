from app.schemas.common import ORMModel


class DemandForecastItem(ORMModel):
    dish_id: int
    name: str
    recent_views: int
    demand_score: float
    demand_level: str
    confidence: str
    explanation: str


class InventoryForecastItem(ORMModel):
    inventory_item_id: int
    name: str
    unit: str
    current_stock: float
    minimum_stock: float
    ideal_stock: float
    demand_pressure: int
    risk_level: str
    explanation: str


class PreparationRecommendation(ORMModel):
    dish_id: int
    name: str
    priority: str
    reason: str


class PurchaseRecommendation(ORMModel):
    inventory_item_id: int
    name: str
    priority: str
    reason: str


class PredictionOverview(ORMModel):
    restaurant_id: int | None = None
    range: str = "30d"
    demand_forecast: list[DemandForecastItem]
    inventory_forecast: list[InventoryForecastItem]
    dishes_likely_to_sell: list[DemandForecastItem]
    ingredients_likely_to_run_low: list[InventoryForecastItem]
    preparation_recommendations: list[PreparationRecommendation]
    purchase_recommendations: list[PurchaseRecommendation]
    confidence_level: str
    explanation: str

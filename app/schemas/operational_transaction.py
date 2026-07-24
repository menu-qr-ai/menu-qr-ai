from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import ORMModel
from app.schemas.prediction import PredictionOverview


class SaleTransactionCreate(ORMModel):
    restaurant_id: int
    dish_id: int
    quantity: float = Field(default=1, gt=0)
    occurred_at: datetime | None = None
    source: str = Field(default="manual", min_length=1, max_length=40)
    reference: str | None = Field(default=None, min_length=1, max_length=160)

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, value: str | None) -> str:
        normalized = str(value or "manual").strip().lower()
        return normalized or "manual"


class ConsumedIngredient(ORMModel):
    inventory_item_id: int
    name: str
    unit: str
    quantity: float
    movement_id: int
    historical_unit_cost: float = 0
    historical_total_cost: float = 0


class SaleTransactionResult(ORMModel):
    restaurant_id: int
    dish_id: int
    dish_name: str
    quantity: float
    occurred_at: datetime
    source: str
    consumed_ingredients: list[ConsumedIngredient]
    movement_ids: list[int]
    analytics_event_id: int
    prediction: PredictionOverview

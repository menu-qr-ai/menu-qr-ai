from datetime import datetime

from app.schemas.common import ORMModel


class IngredientRead(ORMModel):
    id: int
    restaurant_id: int
    name: str
    unit: str
    cost: float | None = None
    is_active: bool = True


class RecipeItemRead(ORMModel):
    id: int
    ingredient: IngredientRead
    quantity: float
    unit: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RecipeRead(ORMModel):
    restaurant_id: int
    dish_id: int
    dish_name: str
    is_complete: bool
    items: list[RecipeItemRead]

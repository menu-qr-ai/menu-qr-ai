from app.schemas.common import ORMModel


class IngredientCostLine(ORMModel):
    ingredient_id: int
    ingredient_name: str
    quantity: float
    unit: str
    unit_cost: float
    line_cost: float
    missing_cost: bool = False


class DishCosting(ORMModel):
    restaurant_id: int
    dish_id: int
    dish_name: str
    sale_price: float
    total_cost: float
    gross_margin: float
    margin_percentage: float | None = None
    has_recipe: bool
    missing_costs: bool
    ingredients_breakdown: list[IngredientCostLine]


class DishCostingList(ORMModel):
    restaurant_id: int
    dishes: list[DishCosting]

from app.schemas.common import ORMModel


class IngredientCostLine(ORMModel):
    ingredient_id: int
    ingredient_name: str
    # Net quantity in the dish, as written in the recipe.
    quantity: float
    unit: str
    unit_cost: float
    line_cost: float
    missing_cost: bool = False
    recipe_line_id: int | None = None
    yield_percentage: float = 100
    # Quantity taken from stock: quantity / yield.
    gross_quantity: float | None = None
    ingredient_unit: str | None = None
    # Legacy lines whose unit differs from the ingredient's: cost is unreliable.
    unit_mismatch: bool = False


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
    # Escandallo figures measured on the price without VAT.
    vat_percentage: float | None = None
    price_without_vat: float | None = None
    food_cost_percentage: float | None = None
    net_margin: float | None = None
    net_margin_percentage: float | None = None
    is_active: bool = True
    category_id: int | None = None


class DishCostingList(ORMModel):
    restaurant_id: int
    dishes: list[DishCosting]

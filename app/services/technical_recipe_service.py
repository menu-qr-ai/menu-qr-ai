from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.exceptions import AppError
from app.models import Dish, DishIngredient, InventoryItem
from app.schemas.inventory import DishIngredientCreate, RECIPE_UNITS
from app.schemas.recipe import IngredientRead, RecipeItemRead, RecipeRead
from app.services.restaurant_service import require_restaurant


def normalize_recipe_unit(unit: str) -> str:
    return str(unit).strip().lower()


def validate_recipe_unit(unit: str) -> str:
    normalized = normalize_recipe_unit(unit)
    if normalized not in RECIPE_UNITS:
        raise AppError(
            "Unidad de receta tecnica no permitida.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_recipe_unit",
        )
    return normalized


def require_recipe_dish(db: Session, restaurant_id: int, dish_id: int) -> Dish:
    dish = db.scalar(select(Dish).where(Dish.id == dish_id, Dish.restaurant_id == restaurant_id))
    if dish is None:
        raise AppError(
            "Plato no encontrado para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="dish_not_found",
        )
    return dish


def require_recipe_ingredient(db: Session, restaurant_id: int, inventory_item_id: int) -> InventoryItem:
    item = db.scalar(
        select(InventoryItem).where(
            InventoryItem.id == inventory_item_id,
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


def ensure_recipe_item_can_be_created(db: Session, payload: DishIngredientCreate) -> DishIngredientCreate:
    require_restaurant(db, payload.restaurant_id)
    require_recipe_dish(db, payload.restaurant_id, payload.dish_id)
    require_recipe_ingredient(db, payload.restaurant_id, payload.inventory_item_id)
    unit = validate_recipe_unit(payload.unit)
    existing = db.scalar(
        select(DishIngredient).where(
            DishIngredient.restaurant_id == payload.restaurant_id,
            DishIngredient.dish_id == payload.dish_id,
            DishIngredient.inventory_item_id == payload.inventory_item_id,
        )
    )
    if existing is not None:
        raise AppError(
            "El ingrediente ya existe en la receta tecnica del plato.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="duplicate_recipe_ingredient",
        )
    return payload.model_copy(update={"unit": unit})


def load_recipe_items(db: Session, restaurant_id: int, dish_id: int) -> list[DishIngredient]:
    return list(
        db.scalars(
            select(DishIngredient)
            .where(DishIngredient.restaurant_id == restaurant_id, DishIngredient.dish_id == dish_id)
            .options(selectinload(DishIngredient.inventory_item))
            .order_by(DishIngredient.id)
        ).all()
    )


def require_recipe_items(db: Session, restaurant_id: int, dish_id: int) -> list[DishIngredient]:
    items = load_recipe_items(db, restaurant_id, dish_id)
    if not items:
        raise AppError(
            "La receta tecnica no puede estar vacia.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="recipe_empty",
        )
    return items


def _recipe_item_to_schema(item: DishIngredient) -> RecipeItemRead:
    ingredient = item.inventory_item
    return RecipeItemRead(
        id=item.id,
        ingredient=IngredientRead(
            id=ingredient.id,
            restaurant_id=ingredient.restaurant_id,
            name=ingredient.name,
            unit=ingredient.unit,
            cost=ingredient.cost,
            is_active=ingredient.is_active,
        ),
        quantity=item.quantity,
        unit=item.unit,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def get_recipe(db: Session, restaurant_id: int, dish_id: int) -> RecipeRead:
    require_restaurant(db, restaurant_id)
    dish = require_recipe_dish(db, restaurant_id, dish_id)
    items = load_recipe_items(db, restaurant_id, dish_id)
    return RecipeRead(
        restaurant_id=restaurant_id,
        dish_id=dish_id,
        dish_name=dish.name,
        is_complete=bool(items),
        items=[_recipe_item_to_schema(item) for item in items],
    )

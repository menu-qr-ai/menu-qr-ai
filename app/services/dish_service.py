from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette import status

from app.core.access import Permission
from app.core.exceptions import AppError
from app.models import Category, Dish, User
from app.schemas.dish import DishCreate, DishPriceUpdate
from app.services.access_service import authorize_restaurant


def create_dish(
    db: Session,
    actor: User,
    restaurant_id: int,
    payload: DishCreate,
) -> Dish:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.RESTAURANT_MANAGE,
    )
    _require_category(db, restaurant_id, payload.category_id)
    dish = Dish(
        **payload.model_dump(),
        restaurant_id=restaurant_id,
    )
    db.add(dish)
    db.commit()
    db.refresh(dish)
    return dish


def update_dish_price(
    db: Session,
    actor: User,
    restaurant_id: int,
    dish_id: int,
    payload: DishPriceUpdate,
) -> Dish:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.RESTAURANT_MANAGE,
    )
    dish = db.scalar(
        select(Dish).where(
            Dish.id == dish_id,
            Dish.restaurant_id == restaurant_id,
        )
    )
    if dish is None:
        raise AppError(
            "Plato no encontrado para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="dish_not_found",
        )
    dish.price = payload.price
    db.commit()
    db.refresh(dish)
    return dish


def _require_category(
    db: Session,
    restaurant_id: int,
    category_id: int,
) -> Category:
    category = db.scalar(
        select(Category).where(
            Category.id == category_id,
            Category.restaurant_id == restaurant_id,
        )
    )
    if category is None:
        raise AppError(
            "Categoria no encontrada para este restaurante.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="category_not_found",
        )
    return category

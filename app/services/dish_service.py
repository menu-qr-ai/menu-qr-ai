from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette import status

from app.core.access import Permission
from app.core.exceptions import AppError
from app.models import Dish, User
from app.schemas.dish import DishCreate, DishPriceUpdate, DishUpdate
from app.services.access_service import authorize_restaurant
from app.services.menu_management_service import require_category


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
    require_category(db, restaurant_id, payload.category_id)
    dish = Dish(
        **payload.model_dump(),
        restaurant_id=restaurant_id,
    )
    db.add(dish)
    db.commit()
    db.refresh(dish)
    return dish


def update_dish(
    db: Session,
    actor: User,
    restaurant_id: int,
    dish_id: int,
    payload: DishUpdate,
) -> Dish:
    authorize_restaurant(
        db,
        actor,
        restaurant_id,
        Permission.RESTAURANT_MANAGE,
    )
    dish = require_dish(db, restaurant_id, dish_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") is None:
        data.pop("name", None)
    if "category_id" in data:
        if data["category_id"] is None:
            data.pop("category_id")
        else:
            require_category(db, restaurant_id, data["category_id"])
    for field in ("description", "ingredients", "allergens", "image"):
        if field in data and data[field] is None:
            data[field] = ""
    if data.get("is_active") is None:
        data.pop("is_active", None)
    if data.get("display_order") is None:
        data.pop("display_order", None)
    for field, value in data.items():
        setattr(dish, field, value)
    db.commit()
    db.refresh(dish)
    return dish


def require_dish(db: Session, restaurant_id: int, dish_id: int) -> Dish:
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

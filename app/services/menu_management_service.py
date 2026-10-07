from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette import status

from app.core.access import Permission
from app.core.exceptions import AppError
from app.core.money import money_to_json
from app.models import Category, Dish, User
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.services.access_service import authorize_restaurant


def get_menu_management(db: Session, actor: User, restaurant_id: int) -> dict:
    """Full menu for staff, hidden dishes included (the public menu filters them)."""
    authorize_restaurant(db, actor, restaurant_id, Permission.MENU_READ)
    dish_counts = dict(
        db.execute(
            select(Dish.category_id, func.count(Dish.id))
            .where(Dish.restaurant_id == restaurant_id)
            .group_by(Dish.category_id)
        ).all()
    )
    categories = db.scalars(
        select(Category)
        .where(Category.restaurant_id == restaurant_id)
        .order_by(Category.display_order, Category.name, Category.id)
    ).all()
    dishes = db.scalars(
        select(Dish)
        .where(Dish.restaurant_id == restaurant_id)
        .order_by(Dish.category_id, Dish.display_order, Dish.name, Dish.id)
    ).all()
    return {
        "restaurant_id": restaurant_id,
        "categories": [
            {
                "id": category.id,
                "restaurant_id": category.restaurant_id,
                "name": category.name,
                "display_order": category.display_order,
                "dish_count": dish_counts.get(category.id, 0),
            }
            for category in categories
        ],
        "dishes": [serialize_management_dish(dish) for dish in dishes],
    }


def serialize_management_dish(dish: Dish) -> dict:
    return {
        "id": dish.id,
        "restaurant_id": dish.restaurant_id,
        "category_id": dish.category_id,
        "name": dish.name,
        "description": dish.description or "",
        "price": money_to_json(dish.price),
        "ingredients": dish.ingredients or "",
        "allergens": dish.allergens or "",
        "image": dish.image or "",
        "display_order": dish.display_order,
        "is_active": dish.is_active,
    }


def create_category(
    db: Session,
    actor: User,
    restaurant_id: int,
    payload: CategoryCreate,
) -> Category:
    authorize_restaurant(db, actor, restaurant_id, Permission.RESTAURANT_MANAGE)
    _ensure_category_name_available(db, restaurant_id, payload.name)
    category = Category(restaurant_id=restaurant_id, **payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_category(
    db: Session,
    actor: User,
    restaurant_id: int,
    category_id: int,
    payload: CategoryUpdate,
) -> Category:
    authorize_restaurant(db, actor, restaurant_id, Permission.RESTAURANT_MANAGE)
    category = require_category(db, restaurant_id, category_id)
    data = {
        field: value
        for field, value in payload.model_dump(exclude_unset=True).items()
        if value is not None
    }
    if "name" in data:
        _ensure_category_name_available(db, restaurant_id, data["name"], category_id=category.id)
    for field, value in data.items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


def delete_category(
    db: Session,
    actor: User,
    restaurant_id: int,
    category_id: int,
) -> None:
    authorize_restaurant(db, actor, restaurant_id, Permission.RESTAURANT_MANAGE)
    category = require_category(db, restaurant_id, category_id)
    has_dishes = db.scalar(
        select(func.count(Dish.id)).where(Dish.category_id == category.id)
    )
    if has_dishes:
        # Dishes are never deleted (order history), so neither is their category.
        raise AppError(
            "La categoria tiene platos. Muevelos a otra categoria antes de borrarla.",
            status_code=status.HTTP_409_CONFLICT,
            code="category_not_empty",
        )
    db.delete(category)
    db.commit()


def require_category(db: Session, restaurant_id: int, category_id: int) -> Category:
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


def _ensure_category_name_available(
    db: Session,
    restaurant_id: int,
    name: str,
    *,
    category_id: int | None = None,
) -> None:
    statement = select(Category.id).where(
        Category.restaurant_id == restaurant_id,
        func.lower(Category.name) == name.lower(),
    )
    if category_id is not None:
        statement = statement.where(Category.id != category_id)
    if db.scalar(statement) is not None:
        raise AppError(
            "Ya existe una categoria con ese nombre.",
            status_code=status.HTTP_409_CONFLICT,
            code="category_name_conflict",
        )

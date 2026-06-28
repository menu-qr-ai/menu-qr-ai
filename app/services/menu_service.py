from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Category, Dish, Restaurant
from app.utils.serialization import serialize_category, serialize_dish


def get_menu_data(db: Session, restaurant_id: int) -> dict:
    restaurant = db.scalar(
        select(Restaurant)
        .where(Restaurant.id == restaurant_id)
        .options(
            selectinload(Restaurant.categories),
            selectinload(Restaurant.dishes),
        )
    )
    categories = db.scalars(
        select(Category)
        .where(Category.restaurant_id == restaurant_id)
        .order_by(Category.name, Category.id)
    ).all()
    dishes = db.scalars(
        select(Dish)
        .where(Dish.restaurant_id == restaurant_id)
        .order_by(Dish.category_id, Dish.name, Dish.id)
    ).all()

    return {
        "restaurant_id": restaurant_id,
        "restaurant_name": restaurant.name if restaurant else "Menu QR AI",
        "categories": [serialize_category(category) for category in categories],
        "dishes": [serialize_dish(dish) for dish in dishes],
    }


def get_public_menu_payload(db: Session, restaurant_id: int) -> dict:
    return get_menu_data(db, restaurant_id)

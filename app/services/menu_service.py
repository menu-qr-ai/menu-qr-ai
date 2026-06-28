from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Category, Dish, Restaurant
from app.services.restaurant_service import get_default_restaurant
from app.utils.serialization import serialize_category, serialize_dish


def _serialize_restaurant_public(restaurant: Restaurant | None, restaurant_id: int) -> dict:
    if restaurant is None:
        return {
            "id": restaurant_id,
            "name": "Menu QR AI",
            "slug": None,
            "description": None,
            "logo_url": None,
            "cover_image_url": None,
            "primary_color": None,
            "accent_color": None,
            "currency": "EUR",
            "default_language": "es",
        }
    return {
        "id": restaurant.id,
        "name": restaurant.name,
        "slug": restaurant.slug,
        "description": restaurant.description,
        "logo_url": restaurant.logo_url,
        "cover_image_url": restaurant.cover_image_url,
        "primary_color": restaurant.primary_color,
        "accent_color": restaurant.accent_color,
        "currency": restaurant.currency or "EUR",
        "default_language": restaurant.default_language or "es",
    }


def get_menu_data(db: Session, restaurant_id: int) -> dict:
    restaurant = db.scalar(
        select(Restaurant)
        .where(Restaurant.id == restaurant_id)
        .options(
            selectinload(Restaurant.categories),
            selectinload(Restaurant.dishes),
        )
    )
    if restaurant is None:
        restaurant = get_default_restaurant(db)
        if restaurant is not None:
            restaurant_id = restaurant.id

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
        "restaurant": _serialize_restaurant_public(restaurant, restaurant_id),
        "categories": [serialize_category(category) for category in categories],
        "dishes": [serialize_dish(dish) for dish in dishes],
    }


def get_public_menu_payload(db: Session, restaurant_id: int) -> dict:
    return get_menu_data(db, restaurant_id)

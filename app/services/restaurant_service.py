import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.models import Restaurant
from app.schemas.restaurant import RestaurantCreate, RestaurantUpdate


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "restaurant"


def _ensure_unique_slug(db: Session, slug: str, restaurant_id: int | None = None) -> str:
    base_slug = slugify(slug)
    candidate = base_slug
    suffix = 2
    while True:
        statement = select(Restaurant).where(Restaurant.slug == candidate)
        if restaurant_id is not None:
            statement = statement.where(Restaurant.id != restaurant_id)
        existing = db.scalar(statement)
        if existing is None:
            return candidate
        candidate = f"{base_slug}-{suffix}"
        suffix += 1


def list_restaurants(db: Session) -> list[Restaurant]:
    return list(db.scalars(select(Restaurant).order_by(Restaurant.name, Restaurant.id)).all())


def get_restaurant(db: Session, restaurant_id: int) -> Restaurant | None:
    return db.scalar(select(Restaurant).where(Restaurant.id == restaurant_id))


def get_restaurant_by_slug(db: Session, slug: str) -> Restaurant | None:
    return db.scalar(select(Restaurant).where(Restaurant.slug == slugify(slug)))


def get_default_restaurant(db: Session) -> Restaurant | None:
    restaurant = db.scalar(select(Restaurant).where(Restaurant.id == 1, Restaurant.is_active.is_(True)))
    if restaurant:
        return restaurant
    return db.scalar(select(Restaurant).where(Restaurant.is_active.is_(True)).order_by(Restaurant.id).limit(1))


def require_restaurant(db: Session, restaurant_id: int) -> Restaurant:
    restaurant = get_restaurant(db, restaurant_id)
    if restaurant is None:
        raise AppError(
            "Restaurante no encontrado.",
            status_code=status.HTTP_404_NOT_FOUND,
            code="restaurant_not_found",
        )
    return restaurant


def create_restaurant(db: Session, payload: RestaurantCreate) -> Restaurant:
    data = payload.model_dump()
    data["slug"] = _ensure_unique_slug(db, data.get("slug") or data["name"])
    now = datetime.utcnow()
    restaurant = Restaurant(**data, created_at=now, updated_at=now)
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def update_restaurant(db: Session, restaurant_id: int, payload: RestaurantUpdate) -> Restaurant:
    restaurant = require_restaurant(db, restaurant_id)
    data = payload.model_dump(exclude_unset=True)
    if "slug" in data and data["slug"]:
        data["slug"] = _ensure_unique_slug(db, data["slug"], restaurant_id=restaurant_id)
    elif "name" in data and not restaurant.slug:
        data["slug"] = _ensure_unique_slug(db, data["name"], restaurant_id=restaurant_id)

    for field, value in data.items():
        setattr(restaurant, field, value)
    restaurant.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(restaurant)
    return restaurant

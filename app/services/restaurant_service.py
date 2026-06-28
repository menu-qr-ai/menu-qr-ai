from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Restaurant


def list_restaurants(db: Session) -> list[Restaurant]:
    return list(db.scalars(select(Restaurant).order_by(Restaurant.id)).all())


def get_restaurant(db: Session, restaurant_id: int) -> Restaurant | None:
    return db.scalar(select(Restaurant).where(Restaurant.id == restaurant_id))


def get_default_restaurant(db: Session) -> Restaurant | None:
    return db.scalar(select(Restaurant).order_by(Restaurant.id).limit(1))

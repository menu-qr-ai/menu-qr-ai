from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import AnalyticsEvent, Category, Dish, Restaurant
from app.utils.demo_seed import DEMO_SLUG


def main() -> None:
    with SessionLocal() as db:
        restaurant = db.scalar(select(Restaurant).where(Restaurant.slug == DEMO_SLUG))
        if restaurant is None:
            print("Demo restaurant not found.")
            return

        db.execute(delete(AnalyticsEvent).where(AnalyticsEvent.restaurant_id == restaurant.id))
        db.execute(delete(Dish).where(Dish.restaurant_id == restaurant.id))
        db.execute(delete(Category).where(Category.restaurant_id == restaurant.id))
        db.delete(restaurant)
        db.commit()
    print("Demo data reset.")


if __name__ == "__main__":
    main()

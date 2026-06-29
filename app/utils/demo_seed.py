import json
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import AnalyticsEvent, Category, Dish, Restaurant
from app.services.restaurant_service import slugify


DEMO_SLUG = "demo-restaurant"
DEMO_RESTAURANT = {
    "name": "Demo Restaurant",
    "slug": DEMO_SLUG,
    "description": "Carta mediterranea de demostracion con datos reales para validar el dashboard.",
    "logo_url": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=240&q=80",
    "cover_image_url": "https://images.unsplash.com/photo-1552566626-52f8b828add9?auto=format&fit=crop&w=1400&q=80",
    "primary_color": "#4E7A62",
    "accent_color": "#D8A64B",
    "phone": "+34 600 000 000",
    "email": "demo@hostai.local",
    "address": "Calle Demo 1",
    "city": "Madrid",
    "country": "Spain",
    "currency": "EUR",
    "default_language": "es",
    "is_active": True,
}

DEMO_MENU = {
    "Entrantes": [
        {
            "name": "Burrata con tomate confitado",
            "description": "Burrata cremosa, tomate confitado, pesto suave y aceite de oliva.",
            "price": 11.5,
            "ingredients": "Burrata, tomate, albahaca, aceite de oliva",
            "allergens": "Lacteos, frutos secos",
            "image": "https://images.unsplash.com/photo-1608897013039-887f21d8c804?auto=format&fit=crop&w=900&q=80",
        },
        {
            "name": "Croquetas de jamon",
            "description": "Croquetas cremosas de jamon iberico con bechamel ligera.",
            "price": 8.9,
            "ingredients": "Jamon, leche, harina, huevo",
            "allergens": "Gluten, lacteos, huevo",
            "image": "https://images.unsplash.com/photo-1619881590738-a111d176d906?auto=format&fit=crop&w=900&q=80",
        },
    ],
    "Principales": [
        {
            "name": "Arroz meloso de setas",
            "description": "Arroz meloso con setas de temporada, parmesano y hierbas frescas.",
            "price": 16.8,
            "ingredients": "Arroz, setas, parmesano, caldo vegetal",
            "allergens": "Lacteos",
            "image": "https://images.unsplash.com/photo-1603133872878-684f208fb84b?auto=format&fit=crop&w=900&q=80",
        },
        {
            "name": "Burger HostAI",
            "description": "Burger de ternera, cheddar, cebolla caramelizada y salsa de la casa.",
            "price": 14.5,
            "ingredients": "Ternera, cheddar, pan brioche, cebolla",
            "allergens": "Gluten, lacteos, sesamo",
            "image": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=900&q=80",
        },
        {
            "name": "Lubina al horno",
            "description": "Lubina al horno con patata panadera, limon y ensalada verde.",
            "price": 19.2,
            "ingredients": "Lubina, patata, limon, aceite de oliva",
            "allergens": "Pescado",
            "image": "https://images.unsplash.com/photo-1559847844-5315695dadae?auto=format&fit=crop&w=900&q=80",
        },
    ],
    "Postres": [
        {
            "name": "Tiramisu clasico",
            "description": "Tiramisu con mascarpone, cafe espresso y cacao.",
            "price": 6.4,
            "ingredients": "Mascarpone, cafe, cacao, bizcocho",
            "allergens": "Gluten, lacteos, huevo",
            "image": "https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?auto=format&fit=crop&w=900&q=80",
        }
    ],
}


def _get_or_create_restaurant(db: Session) -> Restaurant:
    restaurant = db.scalar(select(Restaurant).where(Restaurant.slug == DEMO_SLUG))
    now = datetime.utcnow()
    if restaurant is None:
        restaurant = Restaurant(created_at=now, updated_at=now)
        db.add(restaurant)

    for field, value in DEMO_RESTAURANT.items():
        setattr(restaurant, field, value)
    restaurant.slug = slugify(restaurant.slug or restaurant.name)
    restaurant.updated_at = now
    db.commit()
    db.refresh(restaurant)
    return restaurant


def _get_or_create_category(db: Session, restaurant_id: int, name: str) -> Category:
    category = db.scalar(select(Category).where(Category.restaurant_id == restaurant_id, Category.name == name))
    if category is None:
        category = Category(name=name, restaurant_id=restaurant_id)
        db.add(category)
        db.commit()
        db.refresh(category)
    return category


def _upsert_dish(db: Session, restaurant_id: int, category_id: int, payload: dict) -> Dish:
    dish = db.scalar(select(Dish).where(Dish.restaurant_id == restaurant_id, Dish.name == payload["name"]))
    if dish is None:
        dish = Dish(name=payload["name"], restaurant_id=restaurant_id, category_id=category_id)
        db.add(dish)

    for field in ("description", "price", "ingredients", "allergens", "image"):
        setattr(dish, field, payload[field])
    dish.category_id = category_id
    db.commit()
    db.refresh(dish)
    return dish


def _seed_menu(db: Session, restaurant: Restaurant) -> list[Dish]:
    dishes: list[Dish] = []
    for category_name, category_dishes in DEMO_MENU.items():
        category = _get_or_create_category(db, restaurant.id, category_name)
        for dish_payload in category_dishes:
            dishes.append(_upsert_dish(db, restaurant.id, category.id, dish_payload))
    return dishes


def _add_event(
    db: Session,
    restaurant_id: int,
    event_type: str,
    days_ago: int,
    *,
    dish_id: int | None = None,
    language: str | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AnalyticsEvent(
            restaurant_id=restaurant_id,
            event_type=event_type,
            dish_id=dish_id,
            language=language,
            metadata_json=json.dumps({"demo_seed": True, **(metadata or {})}, separators=(",", ":")),
            created_at=datetime.utcnow() - timedelta(days=days_ago),
        )
    )


def _seed_analytics(db: Session, restaurant: Restaurant, dishes: list[Dish]) -> int:
    db.execute(
        delete(AnalyticsEvent).where(
            AnalyticsEvent.restaurant_id == restaurant.id,
            AnalyticsEvent.metadata_json.contains('"demo_seed":true'),
        )
    )
    dish_cycle = dishes or []
    searches = ["burger", "tiramisu", "sin gluten", "lubina", "croquetas", "vegetariano"]
    languages = ["es", "en", "fr", "de"]

    event_count = 0
    for days_ago in range(30):
        daily_views = 3 + (days_ago % 5)
        for index in range(daily_views):
            _add_event(db, restaurant.id, "menu_view", days_ago, language=languages[index % len(languages)])
            event_count += 1

        if dish_cycle:
            for index, dish in enumerate(dish_cycle[: 2 + (days_ago % 3)]):
                _add_event(db, restaurant.id, "dish_view", days_ago, dish_id=dish.id, language=languages[index % 3])
                event_count += 1

        if days_ago % 2 == 0:
            query = searches[(days_ago // 2) % len(searches)]
            _add_event(db, restaurant.id, "search", days_ago, metadata={"search_query": query})
            event_count += 1

        if days_ago % 3 == 0:
            _add_event(db, restaurant.id, "language_change", days_ago, language=languages[days_ago % len(languages)])
            event_count += 1

        if days_ago % 4 == 0 and dish_cycle:
            _add_event(db, restaurant.id, "translation_request", days_ago, dish_id=dish_cycle[0].id, language="en")
            event_count += 1

    db.commit()
    return event_count


def seed_demo_database(db: Session) -> dict:
    restaurant = _get_or_create_restaurant(db)
    dishes = _seed_menu(db, restaurant)
    event_count = _seed_analytics(db, restaurant, dishes)
    return {
        "restaurant_id": restaurant.id,
        "slug": restaurant.slug,
        "categories": len(DEMO_MENU),
        "dishes": len(dishes),
        "analytics_events": event_count,
    }


def main() -> None:
    with SessionLocal() as db:
        result = seed_demo_database(db)
    print(
        "Demo seed ready: "
        f"restaurant_id={result['restaurant_id']} slug={result['slug']} "
        f"dishes={result['dishes']} analytics_events={result['analytics_events']}"
    )


if __name__ == "__main__":
    main()

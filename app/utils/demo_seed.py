import json
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.money import normalize_money
from app.core.access import RestaurantRole
from app.core.security import hash_password
from app.database import SessionLocal
from app.models import (
    AnalyticsEvent,
    Category,
    Dish,
    DishIngredient,
    InventoryAlert,
    InventoryInsight,
    InventoryItem,
    InventoryMovement,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    User,
    Zone,
)
from app.services.restaurant_service import slugify


DEMO_SLUG = "demo-restaurant"
DEMO_OWNER_EMAIL = "owner@demo.hostai.local"
DEMO_OWNER_PASSWORD = "HostAI-demo-2026"
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
        {
            "name": "Ensalada de salmon",
            "description": "Salmon marinado, lechuga crujiente, tomate y vinagreta de albahaca.",
            "price": 13.8,
            "ingredients": "Salmon, lechuga, tomate, albahaca",
            "allergens": "Pescado",
            "image": "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?auto=format&fit=crop&w=900&q=80",
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
        {
            "name": "Pizza Margarita",
            "description": "Pizza de masa artesana con tomate, mozzarella y albahaca fresca.",
            "price": 12.9,
            "ingredients": "Masa de pizza, tomate, mozzarella, albahaca",
            "allergens": "Gluten, lacteos",
            "image": "https://images.unsplash.com/photo-1604382354936-07c5d9983bd3?auto=format&fit=crop&w=900&q=80",
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

DEMO_INVENTORY_ITEMS = {
    "Mozzarella": {"unit": "g", "stock": 180, "minimum": 250, "ideal": 900, "cost": 4.2, "supplier": "Lacteos Norte"},
    "Tomate": {"unit": "kg", "stock": 6, "minimum": 4, "ideal": 12, "cost": 2.1, "supplier": "Huerta Madrid"},
    "Masa de pizza": {"unit": "unit", "stock": 12, "minimum": 8, "ideal": 20, "cost": 0.8, "supplier": "Obrador Central"},
    "Albahaca": {"unit": "kg", "stock": 0.3, "minimum": 0.5, "ideal": 1.2, "cost": 9.5, "supplier": "Verdes Frescos"},
    "Harina": {"unit": "kg", "stock": 35, "minimum": 10, "ideal": 25, "cost": 1.2, "supplier": "Molino Sur"},
    "Salmon": {"unit": "kg", "stock": 1.2, "minimum": 2, "ideal": 5, "cost": 16.5, "supplier": "Pescados Atlantico"},
    "Lechuga": {"unit": "unit", "stock": 18, "minimum": 6, "ideal": 12, "cost": 0.7, "supplier": "Huerta Madrid"},
    "Cafe": {"unit": "kg", "stock": 4, "minimum": 2, "ideal": 6, "cost": 11.0, "supplier": "Tostador Local"},
    "Leche": {"unit": "l", "stock": 10, "minimum": 6, "ideal": 14, "cost": 1.1, "supplier": "Lacteos Norte"},
    "Mascarpone": {"unit": "kg", "stock": 7, "minimum": 2, "ideal": 4, "cost": 7.8, "supplier": "Lacteos Norte"},
}

DEMO_DISH_INGREDIENTS = {
    "Pizza Margarita": [
        ("Mozzarella", 150, "g"),
        ("Tomate", 0.12, "kg"),
        ("Masa de pizza", 1, "unit"),
        ("Albahaca", 0.02, "kg"),
        ("Harina", 0.25, "kg"),
    ],
    "Tiramisu clasico": [
        ("Mascarpone", 0.12, "kg"),
        ("Cafe", 0.03, "kg"),
        ("Leche", 0.08, "l"),
    ],
    "Ensalada de salmon": [
        ("Salmon", 0.18, "kg"),
        ("Lechuga", 1, "unit"),
        ("Tomate", 0.08, "kg"),
        ("Albahaca", 0.01, "kg"),
    ],
    "Croquetas de jamon": [
        ("Harina", 0.08, "kg"),
        ("Leche", 0.2, "l"),
    ],
    "Burrata con tomate confitado": [
        ("Tomate", 0.18, "kg"),
        ("Albahaca", 0.02, "kg"),
    ],
}

DEMO_DINING_ROOM = {
    "Interior": [
        {"code": "M01", "capacity": 2},
        {"code": "M02", "capacity": 4},
        {"code": "M03", "capacity": 6},
    ],
    "Terraza": [
        {"code": "T01", "capacity": 2},
        {"code": "T02", "capacity": 4},
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

    for field in ("description", "ingredients", "allergens", "image"):
        setattr(dish, field, payload[field])
    dish.price = normalize_money(payload["price"], field_name="El precio")
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
    dishes_by_name = {dish.name: dish for dish in dishes}
    weighted_dishes = [
        dishes_by_name[name]
        for name in (
            "Pizza Margarita",
            "Tiramisu clasico",
            "Burger HostAI",
            "Ensalada de salmon",
            "Croquetas de jamon",
            "Burrata con tomate confitado",
            "Lubina al horno",
        )
        if name in dishes_by_name
    ]
    searches = ["burger", "tiramisu", "sin gluten", "lubina", "croquetas", "vegetariano"]
    languages = ["es", "en", "fr", "de"]

    event_count = 0
    for days_ago in range(30):
        daily_views = 3 + (days_ago % 5)
        for index in range(daily_views):
            _add_event(db, restaurant.id, "menu_view", days_ago, language=languages[index % len(languages)])
            event_count += 1

        if weighted_dishes:
            for index, dish in enumerate(weighted_dishes[: 3 + (days_ago % 4)]):
                _add_event(db, restaurant.id, "dish_view", days_ago, dish_id=dish.id, language=languages[index % 3])
                event_count += 1

        if days_ago % 2 == 0:
            query = searches[(days_ago // 2) % len(searches)]
            _add_event(db, restaurant.id, "search", days_ago, metadata={"search_query": query})
            event_count += 1

        if days_ago % 3 == 0:
            _add_event(db, restaurant.id, "language_change", days_ago, language=languages[days_ago % len(languages)])
            event_count += 1

        if days_ago % 4 == 0 and weighted_dishes:
            _add_event(db, restaurant.id, "translation_request", days_ago, dish_id=weighted_dishes[0].id, language="en")
            event_count += 1

    db.commit()
    return event_count


def _seed_inventory(db: Session, restaurant: Restaurant, dishes: list[Dish]) -> dict[str, int]:
    db.execute(delete(InventoryMovement).where(InventoryMovement.restaurant_id == restaurant.id))
    db.execute(delete(DishIngredient).where(DishIngredient.restaurant_id == restaurant.id))
    db.execute(delete(InventoryAlert).where(InventoryAlert.restaurant_id == restaurant.id))
    db.execute(delete(InventoryInsight).where(InventoryInsight.restaurant_id == restaurant.id))
    db.execute(delete(InventoryItem).where(InventoryItem.restaurant_id == restaurant.id))
    db.flush()

    items_by_name: dict[str, InventoryItem] = {}
    for name, payload in DEMO_INVENTORY_ITEMS.items():
        item = InventoryItem(
            restaurant_id=restaurant.id,
            name=name,
            unit=payload["unit"],
            current_stock=0,
            minimum_stock=payload["minimum"],
            ideal_stock=payload["ideal"],
            cost=payload["cost"],
            supplier=payload["supplier"],
            is_active=True,
        )
        db.add(item)
        db.flush()
        db.add(
            InventoryMovement(
                restaurant_id=restaurant.id,
                inventory_item_id=item.id,
                movement_type="IN",
                quantity=payload["stock"],
                unit=payload["unit"],
                historical_unit_cost=payload["cost"],
                historical_total_cost=round(payload["stock"] * payload["cost"], 2),
                reason="initial_stock",
                origin_type="demo_seed",
                origin_id=str(item.id),
                note="Stock inicial demo",
            )
        )
        item.current_stock = payload["stock"]
        items_by_name[name] = item

    dishes_by_name = {dish.name: dish for dish in dishes}
    relation_count = 0
    for dish_name, ingredients in DEMO_DISH_INGREDIENTS.items():
        dish = dishes_by_name.get(dish_name)
        if dish is None:
            continue
        for ingredient_name, quantity, unit in ingredients:
            item = items_by_name.get(ingredient_name)
            if item is None:
                continue
            db.add(
                DishIngredient(
                    restaurant_id=restaurant.id,
                    dish_id=dish.id,
                    inventory_item_id=item.id,
                    quantity=quantity,
                    unit=unit,
                )
            )
            relation_count += 1

    db.commit()
    return {
        "inventory_items": len(items_by_name),
        "dish_ingredients": relation_count,
        "inventory_movements": len(items_by_name),
    }


def _seed_demo_owner(db: Session, restaurant: Restaurant) -> User:
    user = db.scalar(select(User).where(User.email == DEMO_OWNER_EMAIL))
    if user is None:
        user = User(
            email=DEMO_OWNER_EMAIL,
            hashed_password=hash_password(DEMO_OWNER_PASSWORD),
            full_name="Owner Demo",
            role=RestaurantRole.OWNER.value,
            restaurant_id=restaurant.id,
            is_active=True,
        )
        db.add(user)
        db.flush()

    membership = db.scalar(
        select(RestaurantMembership).where(
            RestaurantMembership.user_id == user.id,
            RestaurantMembership.restaurant_id == restaurant.id,
        )
    )
    if membership is None:
        db.add(
            RestaurantMembership(
                user_id=user.id,
                restaurant_id=restaurant.id,
                role=RestaurantRole.OWNER.value,
                is_active=True,
                created_by_user_id=user.id,
            )
        )
        db.commit()
    return user


def _seed_dining_room(db: Session, restaurant: Restaurant) -> dict[str, int]:
    created_zones = 0
    created_tables = 0
    for zone_order, (zone_name, tables) in enumerate(DEMO_DINING_ROOM.items()):
        zone = db.scalar(
            select(Zone).where(
                Zone.restaurant_id == restaurant.id,
                Zone.name == zone_name,
            )
        )
        if zone is None:
            zone = Zone(
                restaurant_id=restaurant.id,
                name=zone_name,
                display_order=zone_order,
                is_active=True,
            )
            db.add(zone)
            db.flush()
            created_zones += 1

        for table_order, table_payload in enumerate(tables):
            table = db.scalar(
                select(RestaurantTable).where(
                    RestaurantTable.restaurant_id == restaurant.id,
                    RestaurantTable.code == table_payload["code"],
                )
            )
            if table is not None:
                continue
            db.add(
                RestaurantTable(
                    restaurant_id=restaurant.id,
                    zone_id=zone.id,
                    code=table_payload["code"],
                    capacity=table_payload["capacity"],
                    display_order=table_order,
                    is_active=True,
                )
            )
            created_tables += 1

    db.commit()
    return {
        "dining_zones_created": created_zones,
        "dining_tables_created": created_tables,
    }


def seed_demo_database(db: Session) -> dict:
    restaurant = _get_or_create_restaurant(db)
    owner = _seed_demo_owner(db, restaurant)
    dishes = _seed_menu(db, restaurant)
    event_count = _seed_analytics(db, restaurant, dishes)
    inventory_counts = _seed_inventory(db, restaurant, dishes)
    dining_counts = _seed_dining_room(db, restaurant)
    return {
        "restaurant_id": restaurant.id,
        "slug": restaurant.slug,
        "owner_email": owner.email,
        "categories": len(DEMO_MENU),
        "dishes": len(dishes),
        "analytics_events": event_count,
        **inventory_counts,
        **dining_counts,
    }


def main() -> None:
    with SessionLocal() as db:
        result = seed_demo_database(db)
    print(
        "Demo seed ready: "
        f"restaurant_id={result['restaurant_id']} slug={result['slug']} "
        f"dishes={result['dishes']} analytics_events={result['analytics_events']} "
        f"inventory_items={result['inventory_items']}"
    )


if __name__ == "__main__":
    main()

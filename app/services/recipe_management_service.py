from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access import Permission
from app.models import Category, InventoryItem, User
from app.services.access_service import authorize_restaurant
from app.services.costing_service import list_dish_costings
from app.services.restaurant_service import require_restaurant


def get_recipe_management(db: Session, actor: User, restaurant_id: int) -> dict:
    """Recipes and escandallos for every dish, plus what the editor needs."""
    authorize_restaurant(db, actor, restaurant_id, Permission.INVENTORY_WRITE)
    restaurant = require_restaurant(db, restaurant_id)
    categories = db.scalars(
        select(Category)
        .where(Category.restaurant_id == restaurant_id)
        .order_by(Category.display_order, Category.name, Category.id)
    ).all()
    ingredients = db.scalars(
        select(InventoryItem)
        .where(InventoryItem.restaurant_id == restaurant_id, InventoryItem.is_active.is_(True))
        .order_by(InventoryItem.name, InventoryItem.id)
    ).all()
    return {
        "restaurant_id": restaurant_id,
        "currency": restaurant.currency or "EUR",
        "vat_percentage": float(restaurant.vat_percentage or 0),
        "categories": [{"id": category.id, "name": category.name} for category in categories],
        "ingredients": [
            {"id": item.id, "name": item.name, "unit": item.unit, "cost": item.cost}
            for item in ingredients
        ],
        "dishes": list_dish_costings(db, restaurant_id).model_dump(mode="json")["dishes"],
    }

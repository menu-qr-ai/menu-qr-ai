from app.core.money import money_to_json
from app.models import Category, Dish


def serialize_category(category: Category) -> dict:
    return {
        "id": category.id,
        "name": category.name,
    }


def serialize_dish(dish: Dish) -> dict:
    return {
        "id": dish.id,
        "name": dish.name,
        "description": dish.description or "",
        "price": money_to_json(dish.price),
        "ingredients": dish.ingredients or "",
        "allergens": dish.allergens or "",
        "image": dish.image or "",
        "category_id": dish.category_id,
    }

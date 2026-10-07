import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from starlette import status

from app.core.access import Permission
from app.core.exceptions import AppError
from app.models import Dish, DishIngredient, InventoryItem, InventoryMovement, User
from app.services.access_service import authorize_restaurant
from app.services.openai_service import openai_service
from app.services.planning_service import get_inventory_planning
from app.services.restaurant_service import require_restaurant

logger = logging.getLogger("app.leftovers")

SLOW_MOVER_DAYS = 14
WASTE_WINDOW_DAYS = 30
MAX_IDEA_INGREDIENTS = 8
MAX_IDEAS = 4
REASON_RANK = {"waste": 0, "overstock": 1, "slow": 2, "unused": 3}


def get_leftovers(db: Session, actor: User, restaurant_id: int) -> dict:
    """Ingredients worth using up, why, and which menu dishes already use them.

    There are no expiry dates in the model, so risk is inferred from data:
    stock above ideal, slow rotation, recent waste and stock with no recipe.
    """
    authorize_restaurant(db, actor, restaurant_id, Permission.INVENTORY_WRITE)
    planning = {item.inventory_item_id: item for item in get_inventory_planning(db, restaurant_id=restaurant_id).items}
    items = db.scalars(
        select(InventoryItem)
        .where(InventoryItem.restaurant_id == restaurant_id, InventoryItem.is_active.is_(True), InventoryItem.current_stock > 0)
        .order_by(InventoryItem.name)
    ).all()
    wasted = dict(
        db.execute(
            select(InventoryMovement.inventory_item_id, func.sum(InventoryMovement.quantity))
            .where(
                InventoryMovement.restaurant_id == restaurant_id,
                InventoryMovement.movement_type == "WASTE",
                InventoryMovement.created_at >= datetime.utcnow() - timedelta(days=WASTE_WINDOW_DAYS),
            )
            .group_by(InventoryMovement.inventory_item_id)
        ).all()
    )
    links_by_item: dict[int, list[DishIngredient]] = defaultdict(list)
    for link in db.scalars(
        select(DishIngredient)
        .options(selectinload(DishIngredient.dish))
        .where(DishIngredient.restaurant_id == restaurant_id)
    ).all():
        links_by_item[link.inventory_item_id].append(link)

    leftovers = []
    for item in items:
        planned = planning.get(item.id)
        daily = planned.average_daily_consumption if planned else None
        days_of_cover = round(item.current_stock / daily, 1) if daily else None
        reasons = []
        if wasted.get(item.id):
            reasons.append({"code": "waste", "amount": round(wasted[item.id], 3)})
        if item.ideal_stock and item.current_stock > item.ideal_stock:
            reasons.append({"code": "overstock", "amount": round(item.current_stock - item.ideal_stock, 3)})
        if days_of_cover is not None and days_of_cover > SLOW_MOVER_DAYS:
            reasons.append({"code": "slow", "days_of_cover": days_of_cover})
        links = links_by_item.get(item.id, [])
        if not links:
            reasons.append({"code": "unused"})
        if not reasons:
            continue
        leftovers.append(
            {
                "inventory_item_id": item.id,
                "name": item.name,
                "unit": item.unit,
                "current_stock": item.current_stock,
                "ideal_stock": item.ideal_stock,
                "cost": item.cost,
                "average_daily_consumption": daily,
                "days_of_cover": days_of_cover,
                "reasons": reasons,
                "dishes": sorted(
                    (
                        {
                            "dish_id": link.dish_id,
                            "name": link.dish.name,
                            "is_active": link.dish.is_active,
                            # Servings this ingredient alone allows.
                            # Epsilon: 7 // 0.1 is 69 in binary floating point.
                            "servings_possible": math.floor(item.current_stock / link.stock_quantity + 1e-9) if link.stock_quantity else None,
                        }
                        for link in links
                    ),
                    key=lambda dish: (not dish["is_active"], dish["name"]),
                ),
            }
        )
    leftovers.sort(key=lambda entry: (min(REASON_RANK[reason["code"]] for reason in entry["reasons"]), entry["name"]))
    return {
        "restaurant_id": restaurant_id,
        "ai_available": openai_service.is_configured,
        "items": leftovers,
    }


def generate_leftover_ideas(db: Session, actor: User, restaurant_id: int, ingredient_ids: list[int]) -> dict:
    """Ask the AI for dish ideas, then keep only what our data can back.

    The model may only use ingredients we list; anything else is dropped,
    units are forced to the ingredient's unit and the cost is computed here
    from real ingredient costs, never taken from the model.
    """
    authorize_restaurant(db, actor, restaurant_id, Permission.INVENTORY_WRITE)
    restaurant = require_restaurant(db, restaurant_id)
    if not ingredient_ids:
        raise AppError("Elige al menos un ingrediente para aprovechar.", code="leftover_ingredients_required")
    focus = db.scalars(
        select(InventoryItem).where(
            InventoryItem.restaurant_id == restaurant_id,
            InventoryItem.id.in_(ingredient_ids[:MAX_IDEA_INGREDIENTS]),
            InventoryItem.is_active.is_(True),
        )
    ).all()
    if not focus:
        raise AppError("Ingredientes no encontrados en este restaurante.", status_code=status.HTTP_404_NOT_FOUND, code="inventory_item_not_found")
    pantry = db.scalars(
        select(InventoryItem).where(
            InventoryItem.restaurant_id == restaurant_id,
            InventoryItem.is_active.is_(True),
            InventoryItem.current_stock > 0,
        )
    ).all()
    catalogue = {item.id: item for item in [*pantry, *focus]}
    menu = db.scalars(select(Dish.name).where(Dish.restaurant_id == restaurant_id, Dish.is_active.is_(True))).all()

    prompt = json.dumps(
        {
            "restaurante": restaurant.name,
            "aprovechar": [{"id": item.id, "nombre": item.name, "stock": item.current_stock, "unidad": item.unit} for item in focus],
            "despensa": [{"id": item.id, "nombre": item.name, "unidad": item.unit} for item in catalogue.values()],
            "carta_actual": list(menu),
            "instrucciones": (
                f"Propón hasta {MAX_IDEAS} platos o sugerencias del día que aprovechen sobre todo los ingredientes de 'aprovechar'. "
                "Usa SOLO ingredientes de 'despensa' (por id) y cantidades por ración en su unidad. "
                "No repitas platos de 'carta_actual'. Cocina realista de restaurante en España. "
                'Devuelve JSON: {"ideas": [{"nombre": str, "descripcion": str, "por_que": str, '
                '"ingredientes": [{"id": int, "cantidad": number}]}]}'
            ),
        },
        ensure_ascii=False,
    )
    result = openai_service.json_completion(
        system="Eres jefe de cocina y asesor de rentabilidad para restaurantes. Respondes solo con JSON válido.",
        prompt=prompt,
    )
    if result.get("error"):
        return {"ideas": [], "error": "La IA no está disponible ahora mismo. Usa las sugerencias de tu carta mientras tanto."}

    vat = float(restaurant.vat_percentage or 0)
    ideas = []
    for raw in (result.get("ideas") or [])[:MAX_IDEAS]:
        if not isinstance(raw, dict) or not str(raw.get("nombre", "")).strip():
            continue
        lines, cost, missing_cost = [], 0.0, False
        for ingredient in raw.get("ingredientes") or []:
            item = catalogue.get(_as_int(ingredient.get("id")) if isinstance(ingredient, dict) else None)
            amount = _as_positive_float(ingredient.get("cantidad")) if isinstance(ingredient, dict) else None
            if item is None or amount is None:
                continue  # invented ingredient or nonsense quantity
            line_cost = round(amount * item.cost, 2) if item.cost is not None else None
            missing_cost = missing_cost or line_cost is None
            cost += line_cost or 0
            lines.append({"inventory_item_id": item.id, "name": item.name, "quantity": amount, "unit": item.unit, "line_cost": line_cost})
        if not any(line["inventory_item_id"] in {item.id for item in focus} for line in lines):
            continue  # does not actually use what we wanted to use up
        ideas.append(
            {
                "name": str(raw["nombre"]).strip()[:120],
                "description": str(raw.get("descripcion", "")).strip()[:400],
                "why": str(raw.get("por_que", "")).strip()[:300],
                "ingredients": lines,
                "estimated_cost": round(cost, 2),
                "missing_costs": missing_cost,
                # Price for a 30 % food cost, VAT included.
                "suggested_price": round(cost / 0.30 * (1 + vat / 100), 2) if cost else None,
            }
        )
    logger.info("leftover_ideas restaurant_id=%s requested=%s returned=%s", restaurant_id, len(focus), len(ideas))
    return {"ideas": ideas, "error": None if ideas else "La IA no propuso ideas válidas con tus ingredientes. Prueba con otra selección."}


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_positive_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 100_000 else None

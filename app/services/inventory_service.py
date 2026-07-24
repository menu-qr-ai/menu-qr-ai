from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette import status

from app.core.exceptions import AppError
from app.models import Dish, DishIngredient, InventoryItem, InventoryMovement
from app.schemas.inventory import (
    DEFAULT_MOVEMENT_REASON,
    MOVEMENT_TYPES,
    RECIPE_UNITS,
    DishAtRisk,
    DishIngredientCreate,
    InventoryAlertRead,
    InventoryCriticalItem,
    InventoryInsightRead,
    InventoryItemCreate,
    InventoryItemUpdate,
    InventoryMovementCreate,
    InventoryOverview,
    InventoryStatus,
    RecommendedAction,
)
from app.services.dashboard_service import get_dashboard_summary
from app.services.restaurant_service import require_restaurant
from app.services.technical_recipe_service import ensure_recipe_item_can_be_created


def list_inventory_items(db: Session, restaurant_id: int | None = None, active_only: bool = False) -> list[InventoryItem]:
    statement = select(InventoryItem).order_by(InventoryItem.name, InventoryItem.id)
    if restaurant_id is not None:
        statement = statement.where(InventoryItem.restaurant_id == restaurant_id)
    if active_only:
        statement = statement.where(InventoryItem.is_active.is_(True))
    return list(db.scalars(statement).all())


def require_inventory_item(db: Session, item_id: int) -> InventoryItem:
    item = db.scalar(select(InventoryItem).where(InventoryItem.id == item_id))
    if item is None:
        raise AppError("Ingrediente no encontrado.", status_code=status.HTTP_404_NOT_FOUND, code="inventory_item_not_found")
    return item


def create_inventory_item(db: Session, payload: InventoryItemCreate) -> InventoryItem:
    require_restaurant(db, payload.restaurant_id)
    initial_stock = payload.current_stock
    item_data = payload.model_dump()
    item_data["current_stock"] = 0
    item = InventoryItem(**item_data)
    db.add(item)
    db.flush()
    if initial_stock > 0:
        create_inventory_movement_record(
            db,
            InventoryMovementCreate(
                restaurant_id=payload.restaurant_id,
                inventory_item_id=item.id,
                movement_type="IN",
                quantity=initial_stock,
                unit=payload.unit,
                reason="initial_stock",
                origin_type="inventory_item",
                origin_id=str(item.id),
                note="Stock inicial",
            ),
        )
    db.commit()
    db.refresh(item)
    return item


def update_inventory_item(db: Session, item_id: int, payload: InventoryItemUpdate) -> InventoryItem:
    item = require_inventory_item(db, item_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return item


def create_dish_ingredient(db: Session, payload: DishIngredientCreate) -> DishIngredient:
    validated_payload = ensure_recipe_item_can_be_created(db, payload)
    link = DishIngredient(**validated_payload.model_dump())
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def _movement_delta(movement_type: str, quantity: float) -> float:
    if movement_type in {"IN", "PRODUCTION_OUTPUT"}:
        return quantity
    if movement_type in {"OUT", "WASTE", "ADJUSTMENT_NEGATIVE", "PRODUCTION_CONSUME"}:
        return -quantity
    return quantity


def create_inventory_movement_record(db: Session, payload: InventoryMovementCreate) -> InventoryMovement:
    if payload.movement_type not in MOVEMENT_TYPES:
        raise AppError("Tipo de movimiento de inventario no valido.", code="invalid_inventory_movement_type")

    item = db.scalar(
        select(InventoryItem).where(
            InventoryItem.id == payload.inventory_item_id,
            InventoryItem.restaurant_id == payload.restaurant_id,
        )
    )
    if item is None:
        raise AppError("Ingrediente no encontrado para este restaurante.", status_code=status.HTTP_404_NOT_FOUND, code="inventory_item_not_found")

    movement_unit = payload.unit or item.unit
    if movement_unit not in RECIPE_UNITS:
        raise AppError("Unidad de movimiento de inventario no valida.", code="invalid_inventory_movement_unit")

    delta = _movement_delta(payload.movement_type, payload.quantity)
    next_stock = item.current_stock + delta
    if next_stock < 0:
        raise AppError("El movimiento dejaria stock negativo.", code="inventory_stock_negative")

    movement_data = payload.model_dump()
    movement_data["unit"] = movement_unit
    movement_data["reason"] = movement_data["reason"] or DEFAULT_MOVEMENT_REASON
    movement = InventoryMovement(**movement_data)
    item.current_stock = next_stock
    item.updated_at = datetime.utcnow()
    db.add(movement)
    db.flush()
    db.refresh(movement)
    return movement


def create_inventory_movement(db: Session, payload: InventoryMovementCreate) -> InventoryMovement:
    movement = create_inventory_movement_record(db, payload)
    db.commit()
    db.refresh(movement)
    return movement


def _item_alert(item: InventoryItem) -> InventoryAlertRead | None:
    if not item.is_active:
        return None
    if item.current_stock <= 0:
        return InventoryAlertRead(
            restaurant_id=item.restaurant_id,
            inventory_item_id=item.id,
            severity="critical",
            title=f"{item.name} agotado",
            message=f"El stock actual es 0 {item.unit}. Reponer antes del siguiente servicio.",
        )
    if item.minimum_stock and item.current_stock <= item.minimum_stock:
        return InventoryAlertRead(
            restaurant_id=item.restaurant_id,
            inventory_item_id=item.id,
            severity="warning",
            title=f"{item.name} por debajo del minimo",
            message=f"Stock actual: {item.current_stock:g} {item.unit}. Minimo operativo: {item.minimum_stock:g} {item.unit}.",
        )
    return None


def get_inventory_alerts(db: Session, restaurant_id: int | None = None) -> list[InventoryAlertRead]:
    return [alert for item in list_inventory_items(db, restaurant_id, active_only=True) if (alert := _item_alert(item))]


def _dish_interest(db: Session, restaurant_id: int | None, range_value: str | None) -> Counter[int]:
    dashboard = get_dashboard_summary(db, restaurant_id=restaurant_id, range_value=range_value)
    return Counter({metric.dish_id: metric.views for metric in dashboard.top_dishes if metric.dish_id is not None})


def _active_item_ids(items: list[InventoryItem]) -> list[int]:
    return [item.id for item in items if item.id is not None]


def _load_links_for_items(db: Session, items: list[InventoryItem]) -> list[DishIngredient]:
    item_ids = _active_item_ids(items)
    if not item_ids:
        return []
    return list(db.scalars(select(DishIngredient).where(DishIngredient.inventory_item_id.in_(item_ids))).all())


def _dish_names(db: Session, dish_ids: set[int]) -> dict[int, str]:
    if not dish_ids:
        return {}
    return {dish.id: dish.name for dish in db.scalars(select(Dish).where(Dish.id.in_(dish_ids))).all()}


def get_inventory_insights(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> list[InventoryInsightRead]:
    items = list_inventory_items(db, restaurant_id, active_only=True)
    dish_views = _dish_interest(db, restaurant_id, range_value)
    if not items:
        return [
            InventoryInsightRead(
                restaurant_id=restaurant_id or 0,
                insight_type="inventory_setup",
                priority="opportunity",
                title="Activa la lectura operativa",
                message="Anade ingredientes al inventario para que HostAI pueda detectar riesgo de rotura y compras prioritarias.",
            )
        ]

    links = _load_links_for_items(db, items)
    if not links:
        return [
            InventoryInsightRead(
                restaurant_id=restaurant_id or items[0].restaurant_id,
                insight_type="dish_ingredient_setup",
                priority="opportunity",
                title="Conecta ingredientes con platos",
                message="Cuando cada plato tenga sus ingredientes, Operaciones podra avisar que recetas estan en riesgo antes del servicio.",
            )
        ]

    if not dish_views:
        return [
            InventoryInsightRead(
                restaurant_id=restaurant_id or items[0].restaurant_id,
                insight_type="analytics_needed",
                priority="opportunity",
                title="Faltan senales de demanda",
                message="Cuando el menu reciba vistas de platos, HostAI cruzara interes real con stock para recomendar compras y preparacion.",
            )
        ]

    dish_names = _dish_names(db, {link.dish_id for link in links})
    links_by_item: dict[int, list[DishIngredient]] = defaultdict(list)
    for link in links:
        links_by_item[link.inventory_item_id].append(link)

    insights: list[InventoryInsightRead] = []
    for item in items:
        related_links = links_by_item.get(item.id, [])
        total_interest = sum(dish_views.get(link.dish_id, 0) for link in related_links)
        hot_link = max(related_links, key=lambda link: dish_views.get(link.dish_id, 0), default=None)

        if total_interest >= 2 and item.current_stock <= item.minimum_stock:
            dish_name = dish_names.get(hot_link.dish_id, "un plato con demanda") if hot_link else "un plato con demanda"
            insights.append(
                InventoryInsightRead(
                    restaurant_id=item.restaurant_id,
                    inventory_item_id=item.id,
                    dish_id=hot_link.dish_id if hot_link else None,
                    insight_type="critical_stock_interest",
                    priority="critical",
                    title=f"{item.name} necesita compra urgente",
                    message=f"{dish_name} y otros platos relacionados suman {total_interest} vistas recientes con stock en minimo.",
                )
            )
        elif total_interest >= 2 and item.ideal_stock and item.current_stock >= item.ideal_stock:
            dish_name = dish_names.get(hot_link.dish_id, "el plato lider") if hot_link else "el plato lider"
            insights.append(
                InventoryInsightRead(
                    restaurant_id=item.restaurant_id,
                    inventory_item_id=item.id,
                    dish_id=hot_link.dish_id if hot_link else None,
                    insight_type="prepare_more",
                    priority="opportunity",
                    title=f"Oportunidad de preparar {dish_name}",
                    message=f"{item.name} tiene margen de stock y acompana platos con demanda visible.",
                )
            )
        elif total_interest == 0 and item.ideal_stock and item.current_stock > item.ideal_stock:
            insights.append(
                InventoryInsightRead(
                    restaurant_id=item.restaurant_id,
                    inventory_item_id=item.id,
                    insight_type="waste_risk",
                    priority="warning",
                    title=f"Revisar salida de {item.name}",
                    message="Hay stock por encima del ideal sin interes reciente en los platos asociados.",
                )
            )

        if len({link.dish_id for link in related_links}) >= 2 and item.current_stock <= item.minimum_stock:
            insights.append(
                InventoryInsightRead(
                    restaurant_id=item.restaurant_id,
                    inventory_item_id=item.id,
                    insight_type="purchase_priority",
                    priority="high",
                    title=f"Compra prioritaria: {item.name}",
                    message="Este ingrediente es compartido por varios platos y esta por debajo del umbral operativo.",
                )
            )

    return insights or [
        InventoryInsightRead(
            restaurant_id=restaurant_id or items[0].restaurant_id,
            insight_type="stable_inventory",
            priority="healthy",
            title="Operativa estable",
            message="No hay tensiones relevantes entre demanda de platos y stock actual.",
        )
    ]


def get_inventory_overview(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> InventoryOverview:
    items = list_inventory_items(db, restaurant_id)
    active_items = [item for item in items if item.is_active]
    critical = [item for item in active_items if item.current_stock <= 0 or item.current_stock <= item.minimum_stock]
    warning = [
        item
        for item in active_items
        if item not in critical and item.ideal_stock and item.current_stock < item.ideal_stock
    ]
    healthy = [item for item in active_items if item not in critical and item not in warning]
    ideal = [item for item in active_items if item.ideal_stock and item.current_stock >= item.ideal_stock]
    health_percentage = round((len(healthy) / len(active_items)) * 100, 1) if active_items else 0
    alerts = get_inventory_alerts(db, restaurant_id)
    insights = get_inventory_insights(db, restaurant_id, range_value)
    recommended_actions = _recommended_actions(insights, alerts)
    top_critical_items = _top_critical_items(critical)
    dishes_at_risk = _dishes_at_risk(db, critical, restaurant_id, range_value)
    status = InventoryStatus(
        restaurant_id=restaurant_id,
        total_items=len(items),
        active_items=len(active_items),
        critical_items=len(critical),
        warning_items=len(warning),
        healthy_items=len(healthy),
        low_stock_items=len(warning),
        ideal_items=len(ideal),
        inactive_items=len(items) - len(active_items),
        inventory_health_percentage=health_percentage,
    )
    return InventoryOverview(
        restaurant_id=restaurant_id,
        total_items=len(items),
        critical_items=len(critical),
        warning_items=len(warning),
        healthy_items=len(healthy),
        inventory_health_percentage=health_percentage,
        status=status,
        alerts=alerts,
        insights=insights,
        recommended_actions=recommended_actions,
        top_critical_items=top_critical_items,
        dishes_at_risk=dishes_at_risk,
    )


def _top_critical_items(items: list[InventoryItem]) -> list[InventoryCriticalItem]:
    sorted_items = sorted(items, key=lambda item: (item.current_stock - item.minimum_stock, item.name))
    return [
        InventoryCriticalItem(
            id=item.id,
            name=item.name,
            unit=item.unit,
            current_stock=item.current_stock,
            minimum_stock=item.minimum_stock,
            ideal_stock=item.ideal_stock,
            shortage=max(item.minimum_stock - item.current_stock, 0),
        )
        for item in sorted_items[:6]
    ]


def _recommended_actions(
    insights: list[InventoryInsightRead],
    alerts: list[InventoryAlertRead],
) -> list[RecommendedAction]:
    actions: list[RecommendedAction] = []
    for alert in alerts:
        actions.append(
            RecommendedAction(
                title=alert.title,
                message=alert.message,
                priority=alert.severity,
                action_type="replenish_stock",
                inventory_item_id=alert.inventory_item_id,
            )
        )
    for insight in insights:
        if insight.insight_type in {"critical_stock_interest", "purchase_priority", "prepare_more", "waste_risk"}:
            actions.append(
                RecommendedAction(
                    title=insight.title,
                    message=insight.message,
                    priority=insight.priority,
                    action_type=insight.insight_type,
                    inventory_item_id=insight.inventory_item_id,
                    dish_id=insight.dish_id,
                )
            )
    if actions:
        priority_order = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "low": 4}
        return sorted(actions, key=lambda action: priority_order.get(action.priority, 5))[:6]
    return [
        RecommendedAction(
            title="Sin accion urgente",
            message="La operativa no muestra riesgos inmediatos. Mantener seguimiento de stock y demanda.",
            priority="healthy",
            action_type="no_action",
        )
    ]


def _dishes_at_risk(
    db: Session,
    critical_items: list[InventoryItem],
    restaurant_id: int | None,
    range_value: str | None,
) -> list[DishAtRisk]:
    if not critical_items:
        return []
    dish_views = _dish_interest(db, restaurant_id, range_value)
    links = _load_links_for_items(db, critical_items)
    dish_names = _dish_names(db, {link.dish_id for link in links})
    item_names = {item.id: item.name for item in critical_items}
    ingredients_by_dish: dict[int, set[str]] = defaultdict(set)
    for link in links:
        ingredients_by_dish[link.dish_id].add(item_names.get(link.inventory_item_id, "Ingrediente critico"))
    return [
        DishAtRisk(
            dish_id=dish_id,
            name=dish_names.get(dish_id, f"Plato #{dish_id}"),
            views=dish_views.get(dish_id, 0),
            critical_ingredients=sorted(ingredients),
        )
        for dish_id, ingredients in sorted(
            ingredients_by_dish.items(),
            key=lambda item: (dish_views.get(item[0], 0), item[0]),
            reverse=True,
        )[:6]
    ]

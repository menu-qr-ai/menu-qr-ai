import json
from collections import defaultdict
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalyticsEvent, Dish, DishIngredient
from app.schemas.prediction import (
    DemandForecastItem,
    InventoryForecastItem,
    PredictionOverview,
    PreparationRecommendation,
    PurchaseRecommendation,
)
from app.services.dashboard_service import get_dashboard_summary
from app.services.inventory_service import list_inventory_items


MIN_EVENTS_FOR_MEDIUM_CONFIDENCE = 8
MIN_EVENTS_FOR_HIGH_CONFIDENCE = 24


def _confidence(total_demand_signals: int, has_inventory: bool, has_links: bool) -> tuple[str, str]:
    if total_demand_signals == 0:
        return "low", "Todavia no hay vistas de platos suficientes para predecir demanda con seguridad."
    if not has_inventory:
        return "low", "Hay senales de demanda, pero falta inventario para proyectar riesgo operativo."
    if not has_links:
        return "low", "Hay demanda e inventario, pero faltan relaciones plato-ingrediente para predecir consumo."
    if total_demand_signals >= MIN_EVENTS_FOR_HIGH_CONFIDENCE:
        return "high", "Prediccion basada en demanda reciente, inventario actual y recetas conectadas."
    if total_demand_signals >= MIN_EVENTS_FOR_MEDIUM_CONFIDENCE:
        return "medium", "Prediccion util, aunque conviene acumular mas vistas de platos para afinarla."
    return "low", "Primeras senales detectadas; la prediccion se volvera mas fiable con mas actividad real."


def _load_dishes(db: Session, restaurant_id: int | None) -> dict[int, Dish]:
    statement = select(Dish)
    if restaurant_id is not None:
        statement = statement.where(Dish.restaurant_id == restaurant_id)
    return {dish.id: dish for dish in db.scalars(statement).all()}


def _load_links(db: Session, restaurant_id: int | None) -> list[DishIngredient]:
    statement = select(DishIngredient)
    if restaurant_id is not None:
        statement = statement.where(DishIngredient.restaurant_id == restaurant_id)
    return list(db.scalars(statement).all())


def _range_start(range_value: str, now: datetime) -> datetime | None:
    if range_value == "today":
        return datetime.combine(now.date(), time.min)
    if range_value == "7d":
        return now - timedelta(days=7)
    if range_value == "30d":
        return now - timedelta(days=30)
    if range_value == "90d":
        return now - timedelta(days=90)
    return None


def _metadata_dict(metadata_json: str | None) -> dict | None:
    if not metadata_json:
        return None
    try:
        value = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _load_sale_counts(db: Session, restaurant_id: int | None, range_value: str) -> dict[int, float]:
    statement = select(AnalyticsEvent).where(AnalyticsEvent.event_type == "sale_processed")
    if restaurant_id is not None:
        statement = statement.where(AnalyticsEvent.restaurant_id == restaurant_id)
    start = _range_start(range_value, datetime.utcnow())
    if start is not None:
        statement = statement.where(AnalyticsEvent.created_at >= start)

    sale_counts: defaultdict[int, float] = defaultdict(float)
    for event in db.scalars(statement).all():
        if event.dish_id is None:
            continue
        metadata = _metadata_dict(event.metadata_json) or {}
        quantity = metadata.get("quantity", 1)
        try:
            sale_counts[event.dish_id] += float(quantity)
        except (TypeError, ValueError):
            sale_counts[event.dish_id] += 1
    return dict(sale_counts)


def _demand_level(score: float) -> str:
    if score >= 8:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def _risk_level(item_stock: float, minimum_stock: float, ideal_stock: float, demand_pressure: int) -> str:
    if item_stock <= minimum_stock and demand_pressure > 0:
        return "critical"
    if item_stock <= minimum_stock:
        return "warning"
    if ideal_stock and item_stock < ideal_stock and demand_pressure >= 3:
        return "warning"
    if demand_pressure >= 8:
        return "opportunity"
    return "healthy"


def _build_context(db: Session, restaurant_id: int | None, range_value: str | None) -> dict:
    dashboard = get_dashboard_summary(db, restaurant_id=restaurant_id, range_value=range_value)
    dishes = _load_dishes(db, restaurant_id)
    items = list_inventory_items(db, restaurant_id=restaurant_id, active_only=True)
    links = _load_links(db, restaurant_id)
    dish_views = {metric.dish_id: metric.views for metric in dashboard.top_dishes if metric.dish_id is not None}
    sale_counts = _load_sale_counts(db, restaurant_id, dashboard.range)
    search_counts = {metric.query.lower(): metric.count for metric in dashboard.top_searches}
    return {
        "dashboard": dashboard,
        "dishes": dishes,
        "items": items,
        "links": links,
        "dish_views": dish_views,
        "sale_counts": sale_counts,
        "search_counts": search_counts,
    }


def _demand_forecast_from_context(context: dict) -> list[DemandForecastItem]:
    dashboard = context["dashboard"]
    dishes: dict[int, Dish] = context["dishes"]
    dish_views: dict[int, int] = context["dish_views"]
    sale_counts: dict[int, float] = context["sale_counts"]
    search_counts: dict[str, int] = context["search_counts"]
    total_demand_signals = dashboard.summary.total_dish_views + round(sum(sale_counts.values()))
    confidence, _ = _confidence(
        total_demand_signals,
        has_inventory=bool(context["items"]),
        has_links=bool(context["links"]),
    )

    forecasts: list[DemandForecastItem] = []
    for dish_id, dish in dishes.items():
        views = dish_views.get(dish_id, 0)
        sales = sale_counts.get(dish_id, 0)
        search_boost = sum(count for query, count in search_counts.items() if query and query in dish.name.lower())
        score = round((sales * 2.0) + (views * 1.0) + (search_boost * 0.5), 2)
        if score <= 0:
            continue
        level = _demand_level(score)
        explanation_parts = []
        if sales:
            explanation_parts.append(f"{sales:g} ventas reales")
        if views:
            explanation_parts.append(f"{views} vistas recientes")
        if search_boost:
            explanation_parts.append("senales de busqueda relacionadas")
        forecasts.append(
            DemandForecastItem(
                dish_id=dish_id,
                name=dish.name,
                recent_views=views,
                demand_score=score,
                demand_level=level,
                confidence=confidence,
                explanation=f"{dish.name} concentra {', '.join(explanation_parts)}.",
            )
        )
    return sorted(forecasts, key=lambda item: (item.demand_score, item.recent_views), reverse=True)


def get_demand_forecast(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> list[DemandForecastItem]:
    return _demand_forecast_from_context(_build_context(db, restaurant_id, range_value))


def _inventory_forecast_from_context(context: dict) -> list[InventoryForecastItem]:
    items = {item.id: item for item in context["items"]}
    links: list[DishIngredient] = context["links"]
    dish_views: dict[int, int] = context["dish_views"]
    sale_counts: dict[int, float] = context["sale_counts"]
    pressure_by_item: dict[int, int] = defaultdict(int)
    for link in links:
        pressure_by_item[link.inventory_item_id] += round(sale_counts.get(link.dish_id, 0) + dish_views.get(link.dish_id, 0))

    forecast: list[InventoryForecastItem] = []
    for item_id, item in items.items():
        pressure = pressure_by_item.get(item_id, 0)
        risk = _risk_level(item.current_stock, item.minimum_stock, item.ideal_stock, pressure)
        if pressure == 0 and risk == "healthy":
            continue
        forecast.append(
            InventoryForecastItem(
                inventory_item_id=item_id,
                name=item.name,
                unit=item.unit,
                current_stock=item.current_stock,
                minimum_stock=item.minimum_stock,
                ideal_stock=item.ideal_stock,
                demand_pressure=pressure,
                risk_level=risk,
                explanation=f"{item.name} participa en platos con {pressure} vistas recientes y stock actual de {item.current_stock:g} {item.unit}.",
            )
        )
    return sorted(
        forecast,
        key=lambda item: ({"critical": 4, "warning": 3, "opportunity": 2, "healthy": 1}.get(item.risk_level, 0), item.demand_pressure),
        reverse=True,
    )


def get_inventory_forecast(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> list[InventoryForecastItem]:
    return _inventory_forecast_from_context(_build_context(db, restaurant_id, range_value))


def get_prediction_overview(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> PredictionOverview:
    context = _build_context(db, restaurant_id, range_value)
    dashboard = context["dashboard"]
    demand = _demand_forecast_from_context(context)
    inventory = _inventory_forecast_from_context(context)
    total_demand_signals = dashboard.summary.total_dish_views + round(sum(context["sale_counts"].values()))
    confidence, explanation = _confidence(
        total_demand_signals,
        has_inventory=bool(context["items"]),
        has_links=bool(context["links"]),
    )
    critical_item_ids = {item.inventory_item_id for item in inventory if item.risk_level in {"critical", "warning"}}
    links_by_dish: dict[int, list[DishIngredient]] = defaultdict(list)
    for link in context["links"]:
        links_by_dish[link.dish_id].append(link)

    prep_recommendations: list[PreparationRecommendation] = []
    for item in demand[:6]:
        linked_item_ids = {link.inventory_item_id for link in links_by_dish.get(item.dish_id, [])}
        if linked_item_ids & critical_item_ids:
            reason = "Tiene demanda probable, pero algun ingrediente requiere revision antes de preparar mas."
            priority = "warning"
        else:
            reason = "Tiene demanda probable y no muestra bloqueos fuertes de inventario."
            priority = "opportunity" if item.demand_level == "high" else "healthy"
        prep_recommendations.append(
            PreparationRecommendation(dish_id=item.dish_id, name=item.name, priority=priority, reason=reason)
        )

    purchase_recommendations = [
        PurchaseRecommendation(
            inventory_item_id=item.inventory_item_id,
            name=item.name,
            priority=item.risk_level,
            reason=item.explanation,
        )
        for item in inventory
        if item.risk_level in {"critical", "warning"}
    ][:6]

    return PredictionOverview(
        restaurant_id=restaurant_id,
        range=dashboard.range,
        demand_forecast=demand[:8],
        inventory_forecast=inventory[:8],
        dishes_likely_to_sell=[item for item in demand if item.demand_level in {"high", "medium"}][:6],
        ingredients_likely_to_run_low=[item for item in inventory if item.risk_level in {"critical", "warning"}][:6],
        preparation_recommendations=prep_recommendations[:6],
        purchase_recommendations=purchase_recommendations,
        confidence_level=confidence,
        explanation=explanation,
    )

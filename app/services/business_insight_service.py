import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalyticsEvent
from app.schemas.business_insight import (
    BusinessHealthScore,
    BusinessInsightReport,
    BusinessOpportunity,
    BusinessPriority,
    BusinessRisk,
    ExecutiveSummary,
)
from app.schemas.costing import DishCosting, DishCostingList
from app.schemas.dashboard import DashboardResponse
from app.schemas.planning import InventoryPlanningResponse
from app.schemas.prediction import PredictionOverview
from app.services.costing_service import list_dish_costings
from app.services.dashboard_service import get_dashboard_summary
from app.services.planning_service import get_inventory_planning
from app.services.prediction_service import get_prediction_overview
from app.services.restaurant_service import require_restaurant


LOW_MARGIN_PERCENTAGE = 30


@dataclass(frozen=True)
class BusinessInsightContext:
    restaurant_id: int | None
    range: str
    dashboard: DashboardResponse
    prediction: PredictionOverview
    planning: InventoryPlanningResponse
    costing: DishCostingList
    processed_sales: int
    dishes_sold: float


def _metadata_dict(metadata_json: str | None) -> dict:
    if not metadata_json:
        return {}
    try:
        value = json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _sales_metrics(db: Session, restaurant_id: int | None) -> tuple[int, float]:
    statement = select(AnalyticsEvent).where(AnalyticsEvent.event_type == "sale_processed")
    if restaurant_id is not None:
        statement = statement.where(AnalyticsEvent.restaurant_id == restaurant_id)
    events = list(db.scalars(statement).all())
    dishes_sold = 0.0
    for event in events:
        quantity = _metadata_dict(event.metadata_json).get("quantity", 1)
        try:
            dishes_sold += float(quantity)
        except (TypeError, ValueError):
            dishes_sold += 1
    return len(events), round(dishes_sold, 2)


def _load_context(db: Session, restaurant_id: int | None, range_value: str | None) -> BusinessInsightContext:
    if restaurant_id is not None:
        require_restaurant(db, restaurant_id)
    dashboard = get_dashboard_summary(db, restaurant_id=restaurant_id, range_value=range_value)
    planning = get_inventory_planning(db, restaurant_id=restaurant_id, range_value=dashboard.range)
    prediction = get_prediction_overview(db, restaurant_id=restaurant_id, range_value=dashboard.range)
    costing = list_dish_costings(db, restaurant_id) if restaurant_id is not None else DishCostingList(restaurant_id=0, dishes=[])
    processed_sales, dishes_sold = _sales_metrics(db, restaurant_id)
    return BusinessInsightContext(
        restaurant_id=restaurant_id,
        range=dashboard.range,
        dashboard=dashboard,
        prediction=prediction,
        planning=planning,
        costing=costing,
        processed_sales=processed_sales,
        dishes_sold=dishes_sold,
    )


def _money(value: float) -> float:
    return round(value, 2)


def _average_margin(costings: list[DishCosting]) -> float | None:
    margins = [dish.margin_percentage for dish in costings if dish.margin_percentage is not None]
    if not margins:
        return None
    return round(sum(margins) / len(margins), 2)


def _general_status(health: BusinessHealthScore) -> str:
    return health.classification


def _executive_summary(context: BusinessInsightContext, health: BusinessHealthScore) -> ExecutiveSummary:
    return ExecutiveSummary(
        restaurant_id=context.restaurant_id,
        range=context.range,
        processed_sales=context.processed_sales,
        dishes_sold=context.dishes_sold,
        critical_ingredients=context.planning.summary.critical_items + context.planning.summary.out_of_stock_items,
        affected_dishes=sum(item.affected_dishes_count for item in context.planning.items),
        estimated_total_cost=_money(sum(dish.total_cost for dish in context.costing.dishes)),
        average_margin_percentage=_average_margin(context.costing.dishes),
        general_status=_general_status(health),
    )


def _stock_risks(context: BusinessInsightContext) -> list[BusinessRisk]:
    risks: list[BusinessRisk] = []
    for item in context.planning.items:
        if item.status not in {"out_of_stock", "critical", "low"}:
            continue
        severity = "critical" if item.status in {"out_of_stock", "critical"} else "warning"
        risks.append(
            BusinessRisk(
                type="stock",
                severity=severity,
                title=f"Revisar stock de {item.name}",
                explanation=f"Estado operativo: {item.status}. Stock actual: {item.current_stock:g} {item.unit}.",
                impact=f"{item.affected_dishes_count} platos afectados, {item.blocked_dishes_count} bloqueados.",
                inventory_item_id=item.inventory_item_id,
            )
        )
    return risks


def _costing_risks(context: BusinessInsightContext) -> list[BusinessRisk]:
    risks: list[BusinessRisk] = []
    for dish in context.costing.dishes:
        if not dish.has_recipe:
            risks.append(
                BusinessRisk(
                    type="recipe",
                    severity="warning",
                    title=f"Completar receta de {dish.dish_name}",
                    explanation="El plato no tiene receta tecnica conectada.",
                    impact="Costes, margen, stock y prediccion pierden precision.",
                    dish_id=dish.dish_id,
                )
            )
        if dish.missing_costs:
            risks.append(
                BusinessRisk(
                    type="costing",
                    severity="warning",
                    title=f"Revisar costes de {dish.dish_name}",
                    explanation="Hay ingredientes sin coste unitario.",
                    impact="El margen calculado puede estar sobreestimado.",
                    dish_id=dish.dish_id,
                )
            )
        if dish.margin_percentage is not None and dish.margin_percentage < LOW_MARGIN_PERCENTAGE:
            risks.append(
                BusinessRisk(
                    type="margin",
                    severity="warning",
                    title=f"Margen bajo en {dish.dish_name}",
                    explanation=f"Margen actual estimado: {dish.margin_percentage:.2f}%.",
                    impact="Puede reducir la rentabilidad del servicio.",
                    dish_id=dish.dish_id,
                )
            )
    return risks


def _risks(context: BusinessInsightContext) -> list[BusinessRisk]:
    risks = _stock_risks(context) + _costing_risks(context)
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(risks, key=lambda risk: (severity_order.get(risk.severity, 3), risk.type, risk.title))


def _top_profitable_dishes(context: BusinessInsightContext) -> list[BusinessOpportunity]:
    opportunities: list[BusinessOpportunity] = []
    for dish in context.costing.dishes:
        if not dish.has_recipe or dish.margin_percentage is None or dish.gross_margin <= 0:
            continue
        opportunities.append(
            BusinessOpportunity(
                type="profitable_dish",
                title=f"Impulsar {dish.dish_name}",
                explanation=f"Margen estimado de {dish.margin_percentage:.2f}% y margen bruto de {dish.gross_margin:g}.",
                impact="Buen candidato para destacar en carta o recomendaciones.",
                score=round(dish.gross_margin + dish.margin_percentage, 2),
                dish_id=dish.dish_id,
            )
        )
    return sorted(opportunities, key=lambda item: item.score, reverse=True)[:5]


def _replenishment_opportunities(context: BusinessInsightContext) -> list[BusinessOpportunity]:
    opportunities: list[BusinessOpportunity] = []
    for item in context.planning.items:
        if item.affected_dishes_count <= 0:
            continue
        score = (item.affected_dishes_count * 10) + (item.blocked_dishes_count * 20) + item.demand_pressure
        opportunities.append(
            BusinessOpportunity(
                type="inventory_impact",
                title=f"Priorizar {item.name}",
                explanation=f"Este ingrediente afecta a {item.affected_dishes_count} platos.",
                impact=f"Reposicionarlo puede desbloquear {item.blocked_dishes_count} platos.",
                score=score,
                inventory_item_id=item.inventory_item_id,
            )
        )
    return sorted(opportunities, key=lambda item: item.score, reverse=True)[:5]


def _prediction_opportunities(context: BusinessInsightContext) -> list[BusinessOpportunity]:
    return [
        BusinessOpportunity(
            type="predicted_demand",
            title=f"Preparar {dish.name}",
            explanation=dish.explanation,
            impact=f"Nivel de demanda previsto: {dish.demand_level}.",
            score=dish.demand_score,
            dish_id=dish.dish_id,
        )
        for dish in context.prediction.dishes_likely_to_sell[:5]
    ]


def _opportunities(context: BusinessInsightContext) -> list[BusinessOpportunity]:
    opportunities = (
        _top_profitable_dishes(context)
        + _replenishment_opportunities(context)
        + _prediction_opportunities(context)
    )
    return sorted(opportunities, key=lambda item: item.score, reverse=True)[:10]


def _health_score(context: BusinessInsightContext) -> BusinessHealthScore:
    score = 100
    summary = context.planning.summary
    score -= summary.out_of_stock_items * 15
    score -= summary.critical_items * 10
    score -= min(summary.blocked_dishes_count * 8, 24)
    score -= sum(8 for dish in context.costing.dishes if not dish.has_recipe)
    score -= sum(5 for dish in context.costing.dishes if dish.missing_costs)
    score -= sum(
        6
        for dish in context.costing.dishes
        if dish.margin_percentage is not None and dish.margin_percentage < LOW_MARGIN_PERCENTAGE
    )
    score = max(0, min(100, score))
    if score >= 85:
        classification = "Excelente"
    elif score >= 70:
        classification = "Buena"
    elif score >= 45:
        classification = "Mejorable"
    else:
        classification = "Critica"
    return BusinessHealthScore(
        score=score,
        classification=classification,
        explanation="Score basado en stock, recetas, costes, margenes y platos bloqueados.",
    )


def _priority_from_risk(risk: BusinessRisk) -> BusinessPriority:
    return BusinessPriority(
        type=risk.type,
        severity=risk.severity,
        title=risk.title,
        explanation=risk.explanation,
        impact=risk.impact,
        dish_id=risk.dish_id,
        inventory_item_id=risk.inventory_item_id,
    )


def _priorities(context: BusinessInsightContext, risks: list[BusinessRisk]) -> list[BusinessPriority]:
    priorities = [_priority_from_risk(risk) for risk in risks if risk.severity in {"critical", "warning"}]
    if not priorities and context.prediction.preparation_recommendations:
        for recommendation in context.prediction.preparation_recommendations[:3]:
            priorities.append(
                BusinessPriority(
                    type="preparation",
                    severity=recommendation.priority,
                    title=f"Revisar preparacion de {recommendation.name}",
                    explanation=recommendation.reason,
                    impact="Puede ayudar a priorizar mise en place.",
                    dish_id=recommendation.dish_id,
                )
            )
    severity_order = {"critical": 0, "warning": 1, "high": 1, "opportunity": 2, "healthy": 3}
    return sorted(priorities, key=lambda item: (severity_order.get(item.severity, 4), item.title))[:10]


def get_business_insight_report(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> BusinessInsightReport:
    context = _load_context(db, restaurant_id, range_value)
    health = _health_score(context)
    risks = _risks(context)
    priorities = _priorities(context, risks)
    return BusinessInsightReport(
        restaurant_id=restaurant_id,
        range=context.range,
        executive_summary=_executive_summary(context, health),
        health_score=health,
        risks=risks,
        opportunities=_opportunities(context),
        priorities=priorities,
    )


def get_business_health(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> BusinessHealthScore:
    return get_business_insight_report(db, restaurant_id=restaurant_id, range_value=range_value).health_score


def list_business_priorities(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> list[BusinessPriority]:
    return get_business_insight_report(db, restaurant_id=restaurant_id, range_value=range_value).priorities

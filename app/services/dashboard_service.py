import json
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AnalyticsEvent, Dish
from app.schemas.dashboard import (
    DashboardInsight,
    DashboardResponse,
    DashboardSummary,
    LanguageMetric,
    RecentEvent,
    SearchMetric,
    TopDishMetric,
)


SUMMARY_EVENTS = {
    "menu_view": "total_menu_views",
    "dish_view": "total_dish_views",
    "search": "total_searches",
    "language_change": "total_language_changes",
    "translation_request": "total_translation_requests",
}


def _event_filter(statement, restaurant_id: int | None):
    if restaurant_id is None:
        return statement
    return statement.where(AnalyticsEvent.restaurant_id == restaurant_id)


def _metadata_dict(metadata_json: str | None) -> dict[str, Any] | None:
    if not metadata_json:
        return None
    try:
        value = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _summary(db: Session, restaurant_id: int | None) -> DashboardSummary:
    statement = select(AnalyticsEvent.event_type, func.count()).group_by(AnalyticsEvent.event_type)
    rows = db.execute(_event_filter(statement, restaurant_id)).all()
    values = {field: 0 for field in SUMMARY_EVENTS.values()}
    for event_type, count in rows:
        field = SUMMARY_EVENTS.get(event_type)
        if field:
            values[field] = int(count or 0)
    return DashboardSummary(**values)


def _top_dishes(db: Session, restaurant_id: int | None, limit: int = 5) -> list[TopDishMetric]:
    statement = (
        select(AnalyticsEvent.dish_id, Dish.name, func.count().label("views"))
        .outerjoin(Dish, Dish.id == AnalyticsEvent.dish_id)
        .where(AnalyticsEvent.event_type == "dish_view", AnalyticsEvent.dish_id.is_not(None))
        .group_by(AnalyticsEvent.dish_id, Dish.name)
        .order_by(func.count().desc(), AnalyticsEvent.dish_id.asc())
        .limit(limit)
    )
    rows = db.execute(_event_filter(statement, restaurant_id)).all()
    return [
        TopDishMetric(
            dish_id=dish_id,
            name=name or f"Plato #{dish_id}",
            views=int(views or 0),
        )
        for dish_id, name, views in rows
    ]


def _top_searches(db: Session, restaurant_id: int | None, limit: int = 5) -> list[SearchMetric]:
    statement = select(AnalyticsEvent.metadata_json).where(AnalyticsEvent.event_type == "search")
    rows = db.execute(_event_filter(statement, restaurant_id)).all()
    counter: Counter[str] = Counter()
    for (metadata_json,) in rows:
        metadata = _metadata_dict(metadata_json)
        query = (metadata or {}).get("search_query")
        if isinstance(query, str) and query.strip():
            counter[query.strip().lower()] += 1
    return [SearchMetric(query=query, count=count) for query, count in counter.most_common(limit)]


def _languages(db: Session, restaurant_id: int | None, limit: int = 8) -> list[LanguageMetric]:
    statement = (
        select(AnalyticsEvent.language, func.count().label("count"))
        .where(AnalyticsEvent.language.is_not(None), AnalyticsEvent.language != "")
        .group_by(AnalyticsEvent.language)
        .order_by(func.count().desc(), AnalyticsEvent.language.asc())
        .limit(limit)
    )
    rows = db.execute(_event_filter(statement, restaurant_id)).all()
    return [LanguageMetric(language=language, count=int(count or 0)) for language, count in rows]


def _recent_events(db: Session, restaurant_id: int | None, limit: int = 12) -> list[RecentEvent]:
    statement = select(AnalyticsEvent).order_by(AnalyticsEvent.created_at.desc(), AnalyticsEvent.id.desc()).limit(limit)
    events = db.scalars(_event_filter(statement, restaurant_id)).all()
    return [
        RecentEvent(
            id=event.id,
            event_type=event.event_type,
            restaurant_id=event.restaurant_id,
            dish_id=event.dish_id,
            language=event.language,
            metadata=_metadata_dict(event.metadata_json),
            created_at=event.created_at,
        )
        for event in events
    ]


def _insights(
    summary: DashboardSummary,
    top_dishes: list[TopDishMetric],
    top_searches: list[SearchMetric],
) -> list[DashboardInsight]:
    total_events = (
        summary.total_menu_views
        + summary.total_dish_views
        + summary.total_searches
        + summary.total_language_changes
        + summary.total_translation_requests
    )
    if total_events == 0:
        return [
            DashboardInsight(
                title="No hay suficientes datos todavia",
                message="El dashboard empezara a mostrar patrones cuando el menu reciba eventos reales.",
                level="muted",
            )
        ]

    insights: list[DashboardInsight] = []
    if summary.total_menu_views >= 10:
        insights.append(
            DashboardInsight(
                title="El menu recibe muchas visitas",
                message=f"Se han registrado {summary.total_menu_views} visitas al menu.",
                level="success",
            )
        )
    if summary.total_language_changes >= 3:
        insights.append(
            DashboardInsight(
                title="Muchos usuarios cambian de idioma",
                message="Conviene revisar que las traducciones principales esten completas.",
                level="info",
            )
        )
    if top_dishes:
        leader = top_dishes[0]
        insights.append(
            DashboardInsight(
                title="Un plato destaca por visualizaciones",
                message=f"{leader.name} acumula {leader.views} visualizaciones.",
                level="success",
            )
        )
    if top_searches:
        insights.append(
            DashboardInsight(
                title="Existen busquedas frecuentes",
                message=f"La busqueda mas repetida es \"{top_searches[0].query}\".",
                level="info",
            )
        )
    if not insights:
        insights.append(
            DashboardInsight(
                title="No hay suficientes datos todavia",
                message="Ya hay eventos, pero aun faltan volumen y variedad para generar recomendaciones utiles.",
                level="muted",
            )
        )
    return insights


def get_dashboard_summary(db: Session, restaurant_id: int | None = None) -> DashboardResponse:
    summary = _summary(db, restaurant_id)
    top_dishes = _top_dishes(db, restaurant_id)
    top_searches = _top_searches(db, restaurant_id)
    languages = _languages(db, restaurant_id)
    recent_events = _recent_events(db, restaurant_id)
    insights = _insights(summary, top_dishes, top_searches)
    return DashboardResponse(
        restaurant_id=restaurant_id,
        summary=summary,
        top_dishes=top_dishes,
        top_searches=top_searches,
        languages=languages,
        recent_events=recent_events,
        insights=insights,
    )

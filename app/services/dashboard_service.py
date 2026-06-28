import json
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnalyticsEvent, Dish
from app.schemas.dashboard import (
    DailyEventMetric,
    DashboardInsight,
    DashboardResponse,
    DashboardSummary,
    LanguageMetric,
    RecentEvent,
    SearchMetric,
    TopDishMetric,
)


DASHBOARD_RANGES = {"today", "7d", "30d", "90d", "all"}
DEFAULT_DASHBOARD_RANGE = "30d"

SUMMARY_EVENTS = {
    "menu_view": "total_menu_views",
    "dish_view": "total_dish_views",
    "search": "total_searches",
    "language_change": "total_language_changes",
    "translation_request": "total_translation_requests",
}


def normalize_dashboard_range(range_value: str | None) -> str:
    normalized = (range_value or DEFAULT_DASHBOARD_RANGE).strip().lower()
    return normalized if normalized in DASHBOARD_RANGES else DEFAULT_DASHBOARD_RANGE


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


def _metadata_dict(metadata_json: str | None) -> dict[str, Any] | None:
    if not metadata_json:
        return None
    try:
        value = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _load_events(
    db: Session,
    restaurant_id: int | None,
    range_value: str,
) -> list[AnalyticsEvent]:
    statement = select(AnalyticsEvent).order_by(AnalyticsEvent.created_at.desc(), AnalyticsEvent.id.desc())
    if restaurant_id is not None:
        statement = statement.where(AnalyticsEvent.restaurant_id == restaurant_id)
    start = _range_start(range_value, datetime.utcnow())
    if start is not None:
        statement = statement.where(AnalyticsEvent.created_at >= start)
    return list(db.scalars(statement).all())


def _dish_names(db: Session, dish_ids: set[int]) -> dict[int, str]:
    if not dish_ids:
        return {}
    rows = db.execute(select(Dish.id, Dish.name).where(Dish.id.in_(dish_ids))).all()
    return {dish_id: name for dish_id, name in rows}


def _summary(events: list[AnalyticsEvent], top_dishes: list[TopDishMetric]) -> DashboardSummary:
    counts = Counter(event.event_type for event in events)
    menu_views = counts.get("menu_view", 0)
    dish_views = counts.get("dish_view", 0)
    ratio = round(dish_views / menu_views, 2) if menu_views else 0
    leader = top_dishes[0] if top_dishes else None
    return DashboardSummary(
        total_menu_views=menu_views,
        total_dish_views=dish_views,
        total_searches=counts.get("search", 0),
        total_language_changes=counts.get("language_change", 0),
        total_translation_requests=counts.get("translation_request", 0),
        dish_view_menu_view_ratio=ratio,
        top_dish_name=leader.name if leader else None,
        top_dish_views=leader.views if leader else 0,
    )


def _top_dishes(events: list[AnalyticsEvent], dish_names: dict[int, str], limit: int = 5) -> list[TopDishMetric]:
    counter = Counter(event.dish_id for event in events if event.event_type == "dish_view" and event.dish_id)
    return [
        TopDishMetric(
            dish_id=dish_id,
            name=dish_names.get(dish_id, f"Plato #{dish_id}"),
            views=views,
        )
        for dish_id, views in counter.most_common(limit)
    ]


def _top_searches(events: list[AnalyticsEvent], limit: int = 5) -> list[SearchMetric]:
    counter: Counter[str] = Counter()
    for event in events:
        if event.event_type != "search":
            continue
        metadata = _metadata_dict(event.metadata_json)
        query = (metadata or {}).get("search_query")
        if isinstance(query, str) and query.strip():
            counter[query.strip().lower()] += 1
    return [SearchMetric(query=query, count=count) for query, count in counter.most_common(limit)]


def _languages(events: list[AnalyticsEvent], limit: int = 8) -> list[LanguageMetric]:
    counter = Counter(event.language for event in events if event.language)
    total = sum(counter.values())
    return [
        LanguageMetric(
            language=language,
            count=count,
            percentage=round((count / total) * 100, 2) if total else 0,
        )
        for language, count in counter.most_common(limit)
    ]


def _events_by_day(events: list[AnalyticsEvent]) -> list[DailyEventMetric]:
    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {"menu_views": 0, "searches": 0, "translation_requests": 0, "total_events": 0}
    )
    for event in events:
        day = event.created_at.date().isoformat()
        buckets[day]["total_events"] += 1
        if event.event_type == "menu_view":
            buckets[day]["menu_views"] += 1
        elif event.event_type == "search":
            buckets[day]["searches"] += 1
        elif event.event_type == "translation_request":
            buckets[day]["translation_requests"] += 1
    return [DailyEventMetric(date=day, **values) for day, values in sorted(buckets.items())]


def _recent_events(events: list[AnalyticsEvent], limit: int = 12) -> list[RecentEvent]:
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
        for event in events[:limit]
    ]


def _searches_increased(events_by_day: list[DailyEventMetric]) -> bool:
    if len(events_by_day) < 2:
        return False
    midpoint = len(events_by_day) // 2
    previous = sum(day.searches for day in events_by_day[:midpoint])
    current = sum(day.searches for day in events_by_day[midpoint:])
    return current > previous and current > 0


def _insight_no_data() -> list[DashboardInsight]:
    return [
        DashboardInsight(
            title="No hay suficientes datos todavia",
            message="El dashboard empezara a mostrar patrones cuando el menu reciba eventos reales.",
            level="muted",
        )
    ]


def _insights(
    summary: DashboardSummary,
    top_dishes: list[TopDishMetric],
    top_searches: list[SearchMetric],
    languages: list[LanguageMetric],
    events_by_day: list[DailyEventMetric],
) -> list[DashboardInsight]:
    total_events = sum(day.total_events for day in events_by_day)
    if total_events == 0:
        return _insight_no_data()

    insights: list[DashboardInsight] = []
    if summary.total_menu_views < 5:
        insights.append(
            DashboardInsight(
                title="Hay pocas visualizaciones de la carta",
                message="Aun faltan visitas suficientes para leer patrones comerciales con confianza.",
                level="muted",
            )
        )
    elif summary.total_menu_views >= 10:
        insights.append(
            DashboardInsight(
                title="El menu recibe muchas visitas",
                message=f"Se han registrado {summary.total_menu_views} visitas en el rango seleccionado.",
                level="success",
            )
        )

    if languages:
        leader = languages[0]
        insights.append(
            DashboardInsight(
                title=f"El {leader.percentage:.0f}% de los eventos con idioma usan {leader.language}",
                message="Esta distribucion ayuda a priorizar traducciones y contenido localizado.",
                level="info",
            )
        )

    if _searches_increased(events_by_day):
        insights.append(
            DashboardInsight(
                title="Las busquedas aumentaron en el rango seleccionado",
                message="La segunda mitad del periodo concentra mas busquedas que la primera.",
                level="info",
            )
        )

    if top_dishes:
        leader = top_dishes[0]
        insights.append(
            DashboardInsight(
                title="Un plato destaca por numero de visualizaciones",
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

    return insights or _insight_no_data()


def get_dashboard_summary(
    db: Session,
    restaurant_id: int | None = None,
    range_value: str | None = None,
) -> DashboardResponse:
    normalized_range = normalize_dashboard_range(range_value)
    events = _load_events(db, restaurant_id, normalized_range)
    dish_ids = {event.dish_id for event in events if event.dish_id is not None}
    dish_names = _dish_names(db, dish_ids)
    top_dishes = _top_dishes(events, dish_names)
    top_searches = _top_searches(events)
    languages = _languages(events)
    events_by_day = _events_by_day(events)
    summary = _summary(events, top_dishes)
    insights = _insights(summary, top_dishes, top_searches, languages, events_by_day)
    return DashboardResponse(
        restaurant_id=restaurant_id,
        range=normalized_range,
        summary=summary,
        top_dishes=top_dishes,
        top_searches=top_searches,
        languages=languages,
        events_by_day=events_by_day,
        recent_events=_recent_events(events),
        insights=insights,
    )

from datetime import datetime

from app.schemas.common import ORMModel


class DashboardSummary(ORMModel):
    total_menu_views: int = 0
    total_dish_views: int = 0
    total_searches: int = 0
    total_language_changes: int = 0
    total_translation_requests: int = 0
    dish_view_menu_view_ratio: float = 0
    top_dish_name: str | None = None
    top_dish_views: int = 0


class TopDishMetric(ORMModel):
    dish_id: int | None = None
    name: str
    views: int


class SearchMetric(ORMModel):
    query: str
    count: int


class LanguageMetric(ORMModel):
    language: str
    count: int
    percentage: float = 0


class DailyEventMetric(ORMModel):
    date: str
    menu_views: int = 0
    searches: int = 0
    translation_requests: int = 0
    total_events: int = 0


class RecentEvent(ORMModel):
    id: int
    event_type: str
    restaurant_id: int | None = None
    dish_id: int | None = None
    language: str | None = None
    metadata: dict | None = None
    created_at: datetime


class DashboardInsight(ORMModel):
    title: str
    message: str
    level: str = "info"


class DashboardResponse(ORMModel):
    restaurant_id: int | None = None
    range: str = "30d"
    summary: DashboardSummary
    top_dishes: list[TopDishMetric]
    top_searches: list[SearchMetric]
    languages: list[LanguageMetric]
    events_by_day: list[DailyEventMetric]
    recent_events: list[RecentEvent]
    insights: list[DashboardInsight]

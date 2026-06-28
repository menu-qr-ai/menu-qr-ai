from datetime import datetime

from app.schemas.common import ORMModel


class DashboardSummary(ORMModel):
    total_menu_views: int = 0
    total_dish_views: int = 0
    total_searches: int = 0
    total_language_changes: int = 0
    total_translation_requests: int = 0


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
    summary: DashboardSummary
    top_dishes: list[TopDishMetric]
    top_searches: list[SearchMetric]
    languages: list[LanguageMetric]
    recent_events: list[RecentEvent]
    insights: list[DashboardInsight]

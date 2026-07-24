from app.schemas.common import ORMModel


class ExecutiveSummary(ORMModel):
    restaurant_id: int | None = None
    range: str
    processed_sales: int
    dishes_sold: float
    critical_ingredients: int
    affected_dishes: int
    estimated_total_cost: float
    average_margin_percentage: float | None = None
    general_status: str


class BusinessHealthScore(ORMModel):
    score: int
    classification: str
    explanation: str


class BusinessRisk(ORMModel):
    type: str
    severity: str
    title: str
    explanation: str
    impact: str
    dish_id: int | None = None
    inventory_item_id: int | None = None


class BusinessOpportunity(ORMModel):
    type: str
    title: str
    explanation: str
    impact: str
    score: float
    dish_id: int | None = None
    inventory_item_id: int | None = None


class BusinessPriority(ORMModel):
    type: str
    severity: str
    title: str
    explanation: str
    impact: str
    dish_id: int | None = None
    inventory_item_id: int | None = None


class BusinessInsightReport(ORMModel):
    restaurant_id: int | None = None
    range: str
    executive_summary: ExecutiveSummary
    health_score: BusinessHealthScore
    risks: list[BusinessRisk]
    opportunities: list[BusinessOpportunity]
    priorities: list[BusinessPriority]

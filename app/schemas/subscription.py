from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel


class SubscriptionRead(ORMModel):
    id: int
    restaurant_id: int
    plan: str = Field(default="free")
    status: str = Field(default="active")
    provider_customer_id: str | None = None
    provider_subscription_id: str | None = None
    current_period_end: datetime | None = None
    created_at: datetime

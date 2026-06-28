from datetime import datetime

from app.schemas.common import ORMModel


class UsageLogRead(ORMModel):
    id: int
    restaurant_id: int | None = None
    feature: str
    provider: str | None = None
    status: str
    units: int
    created_at: datetime

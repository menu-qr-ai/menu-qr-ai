from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel


class UserRead(ORMModel):
    id: int
    email: str
    full_name: str | None = None
    role: str = Field(default="owner")
    restaurant_id: int | None = None
    created_at: datetime

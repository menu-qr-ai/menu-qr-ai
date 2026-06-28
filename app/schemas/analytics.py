from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app.schemas.common import ORMModel


class AnalyticsEventCreate(ORMModel):
    restaurant_id: int | None = None
    event_type: str = Field(min_length=1, max_length=80)
    dish_id: int | None = None
    language: str | None = Field(default=None, max_length=12)
    metadata: dict[str, Any] | None = None

    @field_validator("event_type", "language", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()


class AnalyticsEventRead(ORMModel):
    id: int
    restaurant_id: int | None = None
    event_type: str
    dish_id: int | None = None
    language: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime

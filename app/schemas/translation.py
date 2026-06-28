from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel


SUPPORTED_LANGUAGES = {"en", "fr", "de", "it", "pt", "es"}


class TranslationRequest(ORMModel):
    language: str = Field(default="en", min_length=2, max_length=8)

    @property
    def normalized_language(self) -> str:
        return self.language.strip().lower()


class TranslationRead(ORMModel):
    id: int
    dish_id: int
    language: str
    name: str
    description: str | None = None
    ingredients: str | None = None
    allergens: str | None = None
    provider: str
    created_at: datetime

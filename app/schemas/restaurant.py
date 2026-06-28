from datetime import datetime

from pydantic import Field, field_validator

from app.schemas.common import ORMModel


class RestaurantBase(ORMModel):
    name: str = Field(min_length=1, max_length=160)
    slug: str | None = Field(default=None, max_length=180)
    description: str | None = None
    logo_url: str | None = None
    cover_image_url: str | None = None
    primary_color: str | None = Field(default=None, max_length=32)
    accent_color: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=180)
    address: str | None = None
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    currency: str = Field(default="EUR", min_length=3, max_length=8)
    default_language: str = Field(default="es", min_length=2, max_length=12)
    is_active: bool = True

    @field_validator("slug", "currency", "default_language", mode="before")
    @classmethod
    def normalize_short_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None


class RestaurantCreate(RestaurantBase):
    pass


class RestaurantUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    slug: str | None = Field(default=None, max_length=180)
    description: str | None = None
    logo_url: str | None = None
    cover_image_url: str | None = None
    primary_color: str | None = Field(default=None, max_length=32)
    accent_color: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=180)
    address: str | None = None
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    currency: str | None = Field(default=None, min_length=3, max_length=8)
    default_language: str | None = Field(default=None, min_length=2, max_length=12)
    is_active: bool | None = None

    @field_validator("slug", "currency", "default_language", mode="before")
    @classmethod
    def normalize_optional_short_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None


class RestaurantRead(RestaurantBase):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RestaurantPublic(ORMModel):
    id: int
    name: str
    slug: str | None = None
    description: str | None = None
    logo_url: str | None = None
    cover_image_url: str | None = None
    primary_color: str | None = None
    accent_color: str | None = None
    currency: str = "EUR"
    default_language: str = "es"

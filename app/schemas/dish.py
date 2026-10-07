from decimal import Decimal

from pydantic import Field, field_validator

from app.core.money import MoneyInput, normalize_money
from app.schemas.common import ORMModel


class DishBase(ORMModel):
    name: str = Field(min_length=1, max_length=180)
    description: str = ""
    price: Decimal | None = None
    ingredients: str = ""
    allergens: str = ""
    image: str = ""
    category_id: int
    display_order: int = Field(default=0, ge=0, le=10_000)
    is_active: bool = True

    @field_validator("description", "ingredients", "allergens", "image", mode="before")
    @classmethod
    def empty_when_none(cls, value: str | None) -> str:
        return value or ""

    @field_validator("price", mode="before")
    @classmethod
    def valid_price(cls, value: MoneyInput | None) -> Decimal | None:
        return normalize_money(
            value,
            nullable=True,
            field_name="El precio",
        )


class DishCreate(DishBase):
    pass


class DishPriceUpdate(ORMModel):
    price: Decimal | None

    @field_validator("price", mode="before")
    @classmethod
    def valid_price(cls, value: MoneyInput | None) -> Decimal | None:
        return normalize_money(
            value,
            nullable=True,
            field_name="El precio",
        )


class DishUpdate(ORMModel):
    """Partial update: only the fields sent are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal | None = None
    ingredients: str | None = Field(default=None, max_length=2000)
    allergens: str | None = Field(default=None, max_length=500)
    image: str | None = Field(default=None, max_length=500)
    category_id: int | None = None
    display_order: int | None = Field(default=None, ge=0, le=10_000)
    is_active: bool | None = None

    @field_validator("price", mode="before")
    @classmethod
    def valid_price(cls, value: MoneyInput | None) -> Decimal | None:
        return normalize_money(
            value,
            nullable=True,
            field_name="El precio",
        )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("El nombre no puede estar vacio.")
        return normalized


class DishRead(DishBase):
    id: int
    restaurant_id: int

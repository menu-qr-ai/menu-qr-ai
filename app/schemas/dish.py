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


class DishRead(DishBase):
    id: int
    restaurant_id: int

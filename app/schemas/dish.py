from pydantic import Field, field_validator

from app.schemas.common import ORMModel


class DishBase(ORMModel):
    name: str = Field(min_length=1, max_length=180)
    description: str = ""
    price: float = Field(default=0, ge=0)
    ingredients: str = ""
    allergens: str = ""
    image: str = ""
    category_id: int
    restaurant_id: int | None = None

    @field_validator("description", "ingredients", "allergens", "image", mode="before")
    @classmethod
    def empty_when_none(cls, value: str | None) -> str:
        return value or ""

    @field_validator("price", mode="before")
    @classmethod
    def zero_when_none(cls, value: float | None) -> float:
        return float(value or 0)


class DishRead(DishBase):
    id: int

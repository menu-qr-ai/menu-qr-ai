from pydantic import Field, field_validator

from app.schemas.common import ORMModel


class CategoryBase(ORMModel):
    name: str = Field(min_length=1, max_length=120)
    restaurant_id: int


class CategoryCreate(ORMModel):
    name: str = Field(min_length=1, max_length=120)
    display_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("El nombre no puede estar vacio.")
        return normalized


class CategoryUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    display_order: int | None = Field(default=None, ge=0, le=10_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("El nombre no puede estar vacio.")
        return normalized


class CategoryRead(CategoryBase):
    id: int
    display_order: int = 0


class CategoryManagementRead(CategoryRead):
    dish_count: int

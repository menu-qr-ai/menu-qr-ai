from pydantic import Field

from app.schemas.common import ORMModel


class CategoryBase(ORMModel):
    name: str = Field(min_length=1, max_length=120)
    restaurant_id: int


class CategoryRead(CategoryBase):
    id: int

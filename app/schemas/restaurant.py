from pydantic import Field

from app.schemas.common import ORMModel


class RestaurantBase(ORMModel):
    name: str = Field(min_length=1, max_length=160)


class RestaurantRead(RestaurantBase):
    id: int

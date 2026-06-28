from app.schemas.category import CategoryRead
from app.schemas.dish import DishRead
from app.schemas.common import ORMModel


class MenuRead(ORMModel):
    restaurant_name: str
    categories: list[CategoryRead]
    dishes: list[DishRead]

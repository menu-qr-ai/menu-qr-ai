from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.access import RestaurantRole
from app.schemas.restaurant import RestaurantRead
from app.schemas.user import UserRead


class MembershipCreate(BaseModel):
    user_id: int
    role: RestaurantRole


class MembershipUpdate(BaseModel):
    role: RestaurantRole | None = None
    is_active: bool | None = None


class RestaurantMembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    restaurant_id: int
    role: RestaurantRole
    is_active: bool
    created_at: datetime
    created_by_user_id: int | None = None


class AccessibleRestaurantRead(BaseModel):
    restaurant: RestaurantRead
    membership: RestaurantMembershipRead


class ActiveRestaurantSelection(BaseModel):
    restaurant_id: int


class AccessContextRead(BaseModel):
    user: UserRead
    active_restaurant: RestaurantRead | None = None
    membership: RestaurantMembershipRead | None = None
    available_restaurants: list[AccessibleRestaurantRead]
    next_url: str

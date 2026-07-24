from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel


class TableQRCodeIssue(ORMModel):
    rotate: bool = False


class TableQRCodeRead(ORMModel):
    table_code: str
    target_url: str
    status: str
    created_at: datetime
    updated_at: datetime


class CustomerRestaurantRead(ORMModel):
    name: str
    currency: str
    logo_url: str | None
    primary_color: str | None
    accent_color: str | None


class CustomerCategoryRead(ORMModel):
    id: int
    name: str


class CustomerDishRead(ORMModel):
    id: int
    category_id: int
    name: str
    description: str
    price: str | None
    ingredients: str
    allergens: str
    image: str
    is_available: bool
    availability_label: str


class CustomerOrderCreate(ORMModel):
    note: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )


class CustomerOrderLineCreate(ORMModel):
    dish_id: int
    quantity: int = Field(default=1, gt=0, le=99)
    note: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )


class CustomerOrderLineUpdate(ORMModel):
    quantity: int | None = Field(default=None, gt=0, le=99)
    note: str | None = Field(default=None, max_length=1000)


class CustomerOrderLineRead(ORMModel):
    id: int
    dish_id: int
    dish_name: str
    quantity: int
    unit_price: str
    note: str | None
    subtotal: str


class CustomerOrderRead(ORMModel):
    status: str
    note: str | None
    lines: list[CustomerOrderLineRead]
    total_amount: str
    total_units: int
    reviewed_at: datetime | None
    rejection_reason: str | None
    created_at: datetime
    updated_at: datetime


class CustomerSessionStateRead(ORMModel):
    status: str
    table_code: str
    expires_at: datetime
    restaurant: CustomerRestaurantRead
    categories: list[CustomerCategoryRead]
    dishes: list[CustomerDishRead]
    orders: list[CustomerOrderRead]


class CustomerOrderReview(ORMModel):
    reason: str | None = Field(default=None, max_length=500)

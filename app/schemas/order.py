from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.core.orders import OrderStatus
from app.core.kitchen import KitchenStatus
from app.core.fulfillment import FulfillmentStatus
from app.schemas.common import ORMModel


class OrderCreate(ORMModel):
    note: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=64)


class OrderLineCreate(ORMModel):
    dish_id: int
    quantity: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=64)


class OrderLineUpdate(ORMModel):
    quantity: int | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)


class OrderLineRead(ORMModel):
    id: int
    restaurant_id: int
    order_id: int
    dish_id: int
    dish_name: str
    quantity: int
    unit_price: Decimal
    note: str | None
    subtotal: Decimal
    created_at: datetime
    updated_at: datetime


class OrderRead(ORMModel):
    id: int
    restaurant_id: int
    service_session_id: int
    status: OrderStatus
    note: str | None
    created_by_user_id: int | None
    is_customer_order: bool
    reviewed_at: datetime | None
    rejection_reason: str | None
    submitted_at: datetime | None
    cancelled_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: list[OrderLineRead]
    total_amount: Decimal
    total_units: int
    kitchen_status: KitchenStatus | None
    fulfillment_status: FulfillmentStatus | None

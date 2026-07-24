from datetime import datetime

from app.core.kitchen import KitchenStatus
from app.schemas.common import ORMModel


class KitchenTicketLineRead(ORMModel):
    id: int
    restaurant_id: int
    kitchen_ticket_id: int
    order_line_id: int
    dish_id: int
    dish_name: str
    quantity: int
    note: str | None
    current_allergens: str | None
    status: KitchenStatus
    started_at: datetime | None
    ready_at: datetime | None
    served_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KitchenTicketRead(ORMModel):
    id: int
    restaurant_id: int
    order_id: int
    service_session_id: int
    table_id: int
    table_code: str
    zone_name: str | None
    status: KitchenStatus
    created_by_user_id: int
    started_at: datetime | None
    ready_at: datetime | None
    served_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: list[KitchenTicketLineRead]

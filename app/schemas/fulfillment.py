from datetime import datetime
from decimal import Decimal

from app.core.fulfillment import FulfillmentLineStatus, FulfillmentStatus
from app.schemas.common import ORMModel


class OrderFulfillmentLineRead(ORMModel):
    order_line_id: int
    kitchen_ticket_line_id: int
    dish_id: int
    quantity: int
    unit_price: Decimal
    status: FulfillmentLineStatus
    operational_reference: str | None
    analytics_event_id: int | None
    movement_ids: list[int]


class OrderFulfillmentRead(ORMModel):
    order_id: int
    fulfillment_id: int
    status: FulfillmentStatus
    executed_at: datetime | None
    executed_by_user_id: int
    processed_lines: list[OrderFulfillmentLineRead]
    skipped_lines: list[OrderFulfillmentLineRead]
    operational_reference: str
    is_idempotent_replay: bool
    error_code: str | None

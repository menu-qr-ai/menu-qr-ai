from datetime import datetime
from decimal import Decimal

from app.core.settlement import SettlementStatus
from app.schemas.common import ORMModel


class ServiceSessionSettlementLineRead(ORMModel):
    order_line_id: int
    fulfillment_line_id: int
    dish_name: str
    quantity: int
    unit_price: Decimal
    subtotal: Decimal


class ServiceSessionSettlementOrderRead(ORMModel):
    order_id: int
    frozen_total: Decimal
    included_line_count: int
    lines: list[ServiceSessionSettlementLineRead]


class ServiceSessionSettlementRead(ORMModel):
    settlement_id: int
    service_session_id: int
    status: SettlementStatus
    currency: str
    subtotal: Decimal
    total: Decimal
    created_by_user_id: int
    finalized_at: datetime
    orders: list[ServiceSessionSettlementOrderRead]
    is_idempotent_replay: bool

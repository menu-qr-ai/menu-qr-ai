from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_serializer

from app.core.money import money_to_json
from app.core.payment import PaymentMethod, PaymentStatus
from app.schemas.common import ORMModel


class PaymentCreate(ORMModel):
    amount: str = Field(min_length=1, max_length=32)
    method: str = Field(min_length=1, max_length=32)
    currency: str | None = Field(default=None, min_length=1, max_length=8)
    reference: str | None = Field(default=None, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)


class PaymentBalanceRead(ORMModel):
    settlement_id: int
    currency: str
    total: Decimal
    amount_paid: Decimal
    amount_remaining: Decimal
    is_fully_paid: bool

    @field_serializer("total", "amount_paid", "amount_remaining")
    def serialize_money(self, value: Decimal) -> str:
        return money_to_json(value)


class PaymentRead(ORMModel):
    payment_id: int
    settlement_id: int
    status: PaymentStatus
    method: PaymentMethod
    amount: Decimal
    currency: str
    reference: str | None
    created_by_user_id: int
    paid_at: datetime

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return money_to_json(value)


class PaymentCreateRead(PaymentRead):
    is_idempotent_replay: bool
    balance: PaymentBalanceRead

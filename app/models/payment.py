from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "status = 'completed'",
            name="ck_payments_status",
        ),
        CheckConstraint(
            "method IN ('cash', 'card', 'other')",
            name="ck_payments_method",
        ),
        CheckConstraint(
            "amount > 0 AND amount <= 9999999999.99",
            name="ck_payments_amount_range",
        ),
        CheckConstraint(
            "length(currency) >= 3 AND length(currency) <= 8",
            name="ck_payments_currency_length",
        ),
        CheckConstraint(
            "length(idempotency_key) > 0",
            name="ck_payments_idempotency_key_not_blank",
        ),
        UniqueConstraint(
            "restaurant_id",
            "idempotency_key",
            name="uq_payments_restaurant_idempotency_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(
        Integer,
        ForeignKey("restaurants.id"),
        nullable=False,
        index=True,
    )
    settlement_id = Column(
        Integer,
        ForeignKey("service_session_settlements.id"),
        nullable=False,
        index=True,
    )
    status = Column(String, nullable=False, default="completed")
    method = Column(String, nullable=False)
    amount = Column(Numeric(precision=12, scale=2), nullable=False)
    currency = Column(String(8), nullable=False)
    reference = Column(String(128), nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )
    paid_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    restaurant = relationship("Restaurant", back_populates="payments")
    settlement = relationship(
        "ServiceSessionSettlement",
        back_populates="payments",
    )
    created_by = relationship("User", back_populates="created_payments")

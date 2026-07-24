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


class ServiceSessionSettlement(Base):
    __tablename__ = "service_session_settlements"
    __table_args__ = (
        CheckConstraint(
            "status = 'finalized'",
            name="ck_service_session_settlements_status",
        ),
        CheckConstraint(
            "subtotal >= 0 AND subtotal <= 9999999999.99",
            name="ck_service_session_settlements_subtotal_range",
        ),
        CheckConstraint(
            "total >= 0 AND total <= 9999999999.99",
            name="ck_service_session_settlements_total_range",
        ),
        UniqueConstraint(
            "service_session_id",
            name="uq_service_session_settlements_session_id",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_service_session_settlements_idempotency_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(
        Integer,
        ForeignKey("restaurants.id"),
        nullable=False,
        index=True,
    )
    service_session_id = Column(
        Integer,
        ForeignKey("service_sessions.id"),
        nullable=False,
        index=True,
    )
    status = Column(String, nullable=False, default="finalized", index=True)
    idempotency_key = Column(String(128), nullable=False)
    currency = Column(String(8), nullable=False)
    subtotal = Column(Numeric(precision=12, scale=2), nullable=False)
    total = Column(Numeric(precision=12, scale=2), nullable=False)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    finalized_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    restaurant = relationship(
        "Restaurant",
        back_populates="service_session_settlements",
    )
    service_session = relationship(
        "ServiceSession",
        back_populates="settlement",
    )
    created_by = relationship(
        "User",
        back_populates="created_service_session_settlements",
    )
    orders = relationship(
        "ServiceSessionSettlementOrder",
        back_populates="settlement",
        cascade="all, delete-orphan",
        order_by="ServiceSessionSettlementOrder.id",
    )
    payments = relationship(
        "Payment",
        back_populates="settlement",
        order_by="Payment.paid_at, Payment.id",
    )


class ServiceSessionSettlementOrder(Base):
    __tablename__ = "service_session_settlement_orders"
    __table_args__ = (
        CheckConstraint(
            "frozen_total >= 0 AND frozen_total <= 9999999999.99",
            name="ck_service_session_settlement_orders_total_range",
        ),
        CheckConstraint(
            "included_line_count > 0",
            name="ck_service_session_settlement_orders_line_count_positive",
        ),
        UniqueConstraint(
            "order_id",
            name="uq_service_session_settlement_orders_order_id",
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
        ForeignKey("service_session_settlements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id = Column(
        Integer,
        ForeignKey("orders.id"),
        nullable=False,
        index=True,
    )
    frozen_total = Column(
        Numeric(precision=12, scale=2),
        nullable=False,
    )
    included_line_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    settlement = relationship(
        "ServiceSessionSettlement",
        back_populates="orders",
    )
    order = relationship("Order", back_populates="settlement_order")
    lines = relationship(
        "ServiceSessionSettlementLine",
        back_populates="settlement_order",
        cascade="all, delete-orphan",
        order_by="ServiceSessionSettlementLine.id",
    )


class ServiceSessionSettlementLine(Base):
    __tablename__ = "service_session_settlement_lines"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0",
            name="ck_service_session_settlement_lines_quantity_positive",
        ),
        CheckConstraint(
            "unit_price >= 0 AND unit_price <= 9999999999.99",
            name="ck_service_session_settlement_lines_unit_price_range",
        ),
        CheckConstraint(
            "subtotal >= 0 AND subtotal <= 9999999999.99",
            name="ck_service_session_settlement_lines_subtotal_range",
        ),
        UniqueConstraint(
            "order_line_id",
            name="uq_service_session_settlement_lines_order_line_id",
        ),
        UniqueConstraint(
            "fulfillment_line_id",
            name="uq_service_session_settlement_lines_fulfillment_line_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(
        Integer,
        ForeignKey("restaurants.id"),
        nullable=False,
        index=True,
    )
    settlement_order_id = Column(
        Integer,
        ForeignKey(
            "service_session_settlement_orders.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    order_line_id = Column(
        Integer,
        ForeignKey("order_lines.id"),
        nullable=False,
        index=True,
    )
    fulfillment_line_id = Column(
        Integer,
        ForeignKey("order_fulfillment_lines.id"),
        nullable=False,
        index=True,
    )
    dish_name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(
        Numeric(precision=12, scale=2),
        nullable=False,
    )
    subtotal = Column(
        Numeric(precision=12, scale=2),
        nullable=False,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    settlement_order = relationship(
        "ServiceSessionSettlementOrder",
        back_populates="lines",
    )
    order_line = relationship(
        "OrderLine",
        back_populates="settlement_line",
    )
    fulfillment_line = relationship(
        "OrderFulfillmentLine",
        back_populates="settlement_line",
    )

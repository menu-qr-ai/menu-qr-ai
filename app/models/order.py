from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.core.money import money_subtotal, sum_money
from app.database import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'draft_customer', "
            "'submitted_customer', 'submitted', 'cancelled', "
            "'completed')",
            name="ck_orders_status",
        ),
        CheckConstraint(
            "((customer_session_id IS NULL AND "
            "created_by_user_id IS NOT NULL) OR "
            "(customer_session_id IS NOT NULL AND "
            "created_by_user_id IS NULL))",
            name="ck_orders_origin_actor",
        ),
        UniqueConstraint(
            "restaurant_id",
            "idempotency_key",
            name="uq_orders_restaurant_idempotency_key",
        ),
        Index(
            "uq_orders_active_customer_session",
            "customer_session_id",
            unique=True,
            sqlite_where=text(
                "customer_session_id IS NOT NULL AND status IN "
                "('draft_customer', 'submitted_customer')"
            ),
            postgresql_where=text(
                "customer_session_id IS NOT NULL AND status IN "
                "('draft_customer', 'submitted_customer')"
            ),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    service_session_id = Column(Integer, ForeignKey("service_sessions.id"), nullable=False, index=True)
    customer_session_id = Column(
        Integer,
        ForeignKey("customer_sessions.id"),
        nullable=True,
        index=True,
    )
    status = Column(String, nullable=False, default="draft", index=True)
    note = Column(Text, nullable=True)
    idempotency_key = Column(String(64), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    reviewed_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="orders")
    service_session = relationship("ServiceSession", back_populates="orders")
    customer_session = relationship(
        "CustomerSession",
        back_populates="orders",
    )
    created_by = relationship(
        "User",
        back_populates="created_orders",
        foreign_keys=[created_by_user_id],
    )
    reviewed_by = relationship(
        "User",
        back_populates="reviewed_customer_orders",
        foreign_keys=[reviewed_by_user_id],
    )
    lines = relationship(
        "OrderLine",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderLine.id",
    )
    kitchen_ticket = relationship("KitchenTicket", back_populates="order", uselist=False)
    fulfillment = relationship(
        "OrderFulfillment",
        back_populates="order",
        uselist=False,
    )
    settlement_order = relationship(
        "ServiceSessionSettlementOrder",
        back_populates="order",
        uselist=False,
    )

    @property
    def total_amount(self) -> Decimal:
        return sum_money(line.subtotal for line in self.lines)

    @property
    def total_units(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def kitchen_status(self) -> str | None:
        return self.kitchen_ticket.status if self.kitchen_ticket is not None else None

    @property
    def fulfillment_status(self) -> str | None:
        return self.fulfillment.status if self.fulfillment is not None else None

    @property
    def is_customer_order(self) -> bool:
        return self.customer_session_id is not None


class OrderLine(Base):
    __tablename__ = "order_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_order_lines_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_order_lines_unit_price_nonnegative"),
        CheckConstraint(
            "unit_price <= 9999999999.99",
            name="ck_order_lines_unit_price_max",
        ),
        UniqueConstraint(
            "order_id",
            "idempotency_key",
            name="uq_order_lines_order_idempotency_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False, index=True)
    dish_name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(precision=12, scale=2), nullable=False)
    note = Column(Text, nullable=True)
    idempotency_key = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="order_lines")
    order = relationship("Order", back_populates="lines")
    dish = relationship("Dish", back_populates="order_lines")
    kitchen_ticket_line = relationship(
        "KitchenTicketLine",
        back_populates="order_line",
        uselist=False,
    )
    fulfillment_line = relationship(
        "OrderFulfillmentLine",
        back_populates="order_line",
        uselist=False,
    )
    settlement_line = relationship(
        "ServiceSessionSettlementLine",
        back_populates="order_line",
        uselist=False,
    )

    @property
    def subtotal(self) -> Decimal:
        return money_subtotal(self.unit_price, self.quantity)

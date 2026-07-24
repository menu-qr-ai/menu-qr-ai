from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class OrderFulfillment(Base):
    __tablename__ = "order_fulfillments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_order_fulfillments_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_order_fulfillments_attempt_count_nonnegative",
        ),
        UniqueConstraint("order_id", name="uq_order_fulfillments_order_id"),
        UniqueConstraint(
            "idempotency_key",
            name="uq_order_fulfillments_idempotency_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    idempotency_key = Column(String(128), nullable=False)
    attempt_count = Column(Integer, nullable=False, default=0)
    executed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    last_attempt_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    failed_at = Column(DateTime, nullable=True)
    error_code = Column(String(80), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="order_fulfillments")
    order = relationship("Order", back_populates="fulfillment")
    executed_by = relationship("User", back_populates="executed_order_fulfillments")
    lines = relationship(
        "OrderFulfillmentLine",
        back_populates="fulfillment",
        cascade="all, delete-orphan",
        order_by="OrderFulfillmentLine.id",
    )


class OrderFulfillmentLine(Base):
    __tablename__ = "order_fulfillment_lines"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processed', 'skipped')",
            name="ck_order_fulfillment_lines_status",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_order_fulfillment_lines_quantity_positive",
        ),
        UniqueConstraint(
            "order_line_id",
            name="uq_order_fulfillment_lines_order_line_id",
        ),
        UniqueConstraint(
            "kitchen_ticket_line_id",
            name="uq_order_fulfillment_lines_kitchen_ticket_line_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    fulfillment_id = Column(
        Integer,
        ForeignKey("order_fulfillments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_line_id = Column(Integer, ForeignKey("order_lines.id"), nullable=False, index=True)
    kitchen_ticket_line_id = Column(
        Integer,
        ForeignKey("kitchen_ticket_lines.id"),
        nullable=False,
        index=True,
    )
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False, index=True)
    quantity = Column(Integer, nullable=False)
    status = Column(String, nullable=False, index=True)
    operational_reference = Column(String(160), nullable=True)
    analytics_event_id = Column(Integer, ForeignKey("analytics_events.id"), nullable=True)
    movement_ids = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    fulfillment = relationship("OrderFulfillment", back_populates="lines")
    order_line = relationship("OrderLine", back_populates="fulfillment_line")
    kitchen_ticket_line = relationship(
        "KitchenTicketLine",
        back_populates="fulfillment_line",
    )
    settlement_line = relationship(
        "ServiceSessionSettlementLine",
        back_populates="fulfillment_line",
        uselist=False,
    )

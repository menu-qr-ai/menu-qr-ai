from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class KitchenTicket(Base):
    __tablename__ = "kitchen_tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'preparing', 'ready', 'served', 'cancelled')",
            name="ck_kitchen_tickets_status",
        ),
        UniqueConstraint("order_id", name="uq_kitchen_tickets_order_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    service_session_id = Column(Integer, ForeignKey("service_sessions.id"), nullable=False, index=True)
    table_id = Column(Integer, ForeignKey("restaurant_tables.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    ready_at = Column(DateTime, nullable=True)
    served_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="kitchen_tickets")
    order = relationship("Order", back_populates="kitchen_ticket")
    service_session = relationship("ServiceSession", back_populates="kitchen_tickets")
    table = relationship("RestaurantTable", back_populates="kitchen_tickets")
    created_by = relationship("User", back_populates="created_kitchen_tickets")
    lines = relationship(
        "KitchenTicketLine",
        back_populates="kitchen_ticket",
        cascade="all, delete-orphan",
        order_by="KitchenTicketLine.id",
    )

    @property
    def table_code(self) -> str:
        return self.table.code

    @property
    def zone_name(self) -> str | None:
        return self.table.zone.name if self.table.zone is not None else None


class KitchenTicketLine(Base):
    __tablename__ = "kitchen_ticket_lines"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'preparing', 'ready', 'served', 'cancelled')",
            name="ck_kitchen_ticket_lines_status",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_kitchen_ticket_lines_quantity_positive",
        ),
        UniqueConstraint(
            "order_line_id",
            name="uq_kitchen_ticket_lines_order_line_id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    kitchen_ticket_id = Column(Integer, ForeignKey("kitchen_tickets.id"), nullable=False, index=True)
    order_line_id = Column(Integer, ForeignKey("order_lines.id"), nullable=False, index=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False, index=True)
    dish_name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    note = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending", index=True)
    started_at = Column(DateTime, nullable=True)
    ready_at = Column(DateTime, nullable=True)
    served_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="kitchen_ticket_lines")
    kitchen_ticket = relationship("KitchenTicket", back_populates="lines")
    order_line = relationship("OrderLine", back_populates="kitchen_ticket_line")
    dish = relationship("Dish", back_populates="kitchen_ticket_lines")
    fulfillment_line = relationship(
        "OrderFulfillmentLine",
        back_populates="kitchen_ticket_line",
        uselist=False,
    )

    @property
    def current_allergens(self) -> str | None:
        return self.dish.allergens

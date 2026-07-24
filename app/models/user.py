from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, unique=True, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String)
    # Legacy compatibility fields. RestaurantMembership is the authorization source of truth.
    role = Column(String, nullable=False, default="owner")
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="users")
    memberships = relationship(
        "RestaurantMembership",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="RestaurantMembership.user_id",
    )
    created_memberships = relationship(
        "RestaurantMembership",
        back_populates="created_by",
        foreign_keys="RestaurantMembership.created_by_user_id",
    )
    opened_service_sessions = relationship(
        "ServiceSession",
        back_populates="opened_by",
        foreign_keys="ServiceSession.opened_by_user_id",
    )
    closed_service_sessions = relationship(
        "ServiceSession",
        back_populates="closed_by",
        foreign_keys="ServiceSession.closed_by_user_id",
    )
    created_orders = relationship(
        "Order",
        back_populates="created_by",
        foreign_keys="Order.created_by_user_id",
    )
    reviewed_customer_orders = relationship(
        "Order",
        back_populates="reviewed_by",
        foreign_keys="Order.reviewed_by_user_id",
    )
    created_kitchen_tickets = relationship("KitchenTicket", back_populates="created_by")
    executed_order_fulfillments = relationship(
        "OrderFulfillment",
        back_populates="executed_by",
    )
    created_service_session_settlements = relationship(
        "ServiceSessionSettlement",
        back_populates="created_by",
    )
    created_payments = relationship(
        "Payment",
        back_populates="created_by",
    )

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True)
    description = Column(Text)
    logo_url = Column(String)
    cover_image_url = Column(String)
    primary_color = Column(String)
    accent_color = Column(String)
    phone = Column(String)
    email = Column(String)
    address = Column(String)
    city = Column(String)
    country = Column(String)
    currency = Column(String, nullable=False, default="EUR")
    default_language = Column(String, nullable=False, default="es")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    categories = relationship("Category", back_populates="restaurant", cascade="all, delete-orphan")
    dishes = relationship("Dish", back_populates="restaurant", cascade="all, delete-orphan")
    users = relationship("User", back_populates="restaurant")
    memberships = relationship("RestaurantMembership", back_populates="restaurant", cascade="all, delete-orphan")
    zones = relationship("Zone", back_populates="restaurant", cascade="all, delete-orphan")
    dining_tables = relationship("RestaurantTable", back_populates="restaurant", cascade="all, delete-orphan")
    service_sessions = relationship("ServiceSession", back_populates="restaurant")
    service_session_settlements = relationship(
        "ServiceSessionSettlement",
        back_populates="restaurant",
    )
    payments = relationship("Payment", back_populates="restaurant")
    orders = relationship("Order", back_populates="restaurant")
    order_lines = relationship("OrderLine", back_populates="restaurant")
    order_fulfillments = relationship("OrderFulfillment", back_populates="restaurant")
    kitchen_tickets = relationship("KitchenTicket", back_populates="restaurant")
    kitchen_ticket_lines = relationship("KitchenTicketLine", back_populates="restaurant")
    subscriptions = relationship("Subscription", back_populates="restaurant", cascade="all, delete-orphan")
    qr_codes = relationship("QRCode", back_populates="restaurant", cascade="all, delete-orphan")
    customer_sessions = relationship(
        "CustomerSession",
        back_populates="restaurant",
    )
    usage_logs = relationship("UsageLog", back_populates="restaurant", cascade="all, delete-orphan")
    inventory_items = relationship("InventoryItem", back_populates="restaurant", cascade="all, delete-orphan")
    dish_ingredients = relationship("DishIngredient", back_populates="restaurant", cascade="all, delete-orphan")
    inventory_movements = relationship("InventoryMovement", back_populates="restaurant", cascade="all, delete-orphan")
    inventory_alerts = relationship("InventoryAlert", back_populates="restaurant", cascade="all, delete-orphan")
    inventory_insights = relationship("InventoryInsight", back_populates="restaurant", cascade="all, delete-orphan")

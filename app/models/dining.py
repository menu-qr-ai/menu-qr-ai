from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Zone(Base):
    __tablename__ = "restaurant_zones"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "name", name="uq_restaurant_zones_restaurant_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    display_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="zones")
    tables = relationship("RestaurantTable", back_populates="zone")


class RestaurantTable(Base):
    __tablename__ = "restaurant_tables"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "code", name="uq_restaurant_tables_restaurant_code"),
        CheckConstraint("capacity > 0", name="ck_restaurant_tables_capacity_positive"),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    zone_id = Column(Integer, ForeignKey("restaurant_zones.id"), nullable=True, index=True)
    code = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False)
    display_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="dining_tables")
    zone = relationship("Zone", back_populates="tables")
    service_sessions = relationship("ServiceSession", back_populates="table")
    kitchen_tickets = relationship("KitchenTicket", back_populates="table")
    customer_sessions = relationship(
        "CustomerSession",
        back_populates="table",
    )
    qr_codes = relationship(
        "QRCode",
        back_populates="table",
    )


class ServiceSession(Base):
    __tablename__ = "service_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'closed', 'cancelled')",
            name="ck_service_sessions_status",
        ),
        CheckConstraint(
            "guest_count IS NULL OR guest_count > 0",
            name="ck_service_sessions_guest_count_positive",
        ),
        CheckConstraint(
            "(status = 'open' AND closed_at IS NULL) OR "
            "(status IN ('closed', 'cancelled') AND closed_at IS NOT NULL)",
            name="ck_service_sessions_closed_at",
        ),
        Index(
            "uq_service_sessions_open_table",
            "table_id",
            unique=True,
            sqlite_where=text("status = 'open'"),
            postgresql_where=text("status = 'open'"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    table_id = Column(Integer, ForeignKey("restaurant_tables.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="open", index=True)
    opened_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    closed_at = Column(DateTime, nullable=True)
    guest_count = Column(Integer, nullable=True)
    opened_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    closed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="service_sessions")
    table = relationship("RestaurantTable", back_populates="service_sessions")
    orders = relationship("Order", back_populates="service_session")
    kitchen_tickets = relationship("KitchenTicket", back_populates="service_session")
    customer_sessions = relationship(
        "CustomerSession",
        back_populates="service_session",
    )
    settlement = relationship(
        "ServiceSessionSettlement",
        back_populates="service_session",
        uselist=False,
    )
    opened_by = relationship(
        "User",
        back_populates="opened_service_sessions",
        foreign_keys=[opened_by_user_id],
    )
    closed_by = relationship(
        "User",
        back_populates="closed_service_sessions",
        foreign_keys=[closed_by_user_id],
    )

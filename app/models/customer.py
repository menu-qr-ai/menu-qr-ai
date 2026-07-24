from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class CustomerSession(Base):
    __tablename__ = "customer_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name="ck_customer_sessions_status",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_customer_sessions_expiry",
        ),
        Index(
            "uq_customer_sessions_active_service_session",
            "service_session_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(
        Integer,
        ForeignKey("restaurants.id"),
        nullable=False,
        index=True,
    )
    table_id = Column(
        Integer,
        ForeignKey("restaurant_tables.id"),
        nullable=False,
        index=True,
    )
    service_session_id = Column(
        Integer,
        ForeignKey("service_sessions.id"),
        nullable=False,
        index=True,
    )
    session_token = Column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    status = Column(
        String(16),
        nullable=False,
        default="active",
        index=True,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    last_activity_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)

    restaurant = relationship(
        "Restaurant",
        back_populates="customer_sessions",
    )
    table = relationship(
        "RestaurantTable",
        back_populates="customer_sessions",
    )
    service_session = relationship(
        "ServiceSession",
        back_populates="customer_sessions",
    )
    orders = relationship(
        "Order",
        back_populates="customer_session",
    )

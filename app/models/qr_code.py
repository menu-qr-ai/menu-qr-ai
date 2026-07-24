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


class QRCode(Base):
    __tablename__ = "qr_codes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_qr_codes_status",
        ),
        Index(
            "uq_qr_codes_active_table",
            "table_id",
            unique=True,
            sqlite_where=text(
                "table_id IS NOT NULL AND status = 'active'"
            ),
            postgresql_where=text(
                "table_id IS NOT NULL AND status = 'active'"
            ),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    table_id = Column(
        Integer,
        ForeignKey("restaurant_tables.id"),
        nullable=True,
        index=True,
    )
    access_token = Column(
        String(64),
        nullable=True,
        unique=True,
        index=True,
    )
    target_url = Column(String, nullable=False)
    image_path = Column(String)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    revoked_at = Column(DateTime, nullable=True)

    restaurant = relationship("Restaurant", back_populates="qr_codes")
    table = relationship("RestaurantTable", back_populates="qr_codes")

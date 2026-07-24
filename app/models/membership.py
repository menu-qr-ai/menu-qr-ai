from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class RestaurantMembership(Base):
    __tablename__ = "restaurant_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "restaurant_id", name="uq_restaurant_memberships_user_restaurant"),
        CheckConstraint(
            "role IN ('owner', 'manager', 'waiter', 'cook', 'viewer')",
            name="ck_restaurant_memberships_role",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    user = relationship("User", back_populates="memberships", foreign_keys=[user_id])
    restaurant = relationship("Restaurant", back_populates="memberships")
    created_by = relationship("User", back_populates="created_memberships", foreign_keys=[created_by_user_id])

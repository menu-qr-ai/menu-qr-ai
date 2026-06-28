from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    plan = Column(String, nullable=False, default="free")
    status = Column(String, nullable=False, default="active")
    provider_customer_id = Column(String, index=True)
    provider_subscription_id = Column(String, index=True)
    current_period_end = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="subscriptions")


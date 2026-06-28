from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    categories = relationship("Category", back_populates="restaurant", cascade="all, delete-orphan")
    dishes = relationship("Dish", back_populates="restaurant", cascade="all, delete-orphan")
    users = relationship("User", back_populates="restaurant")
    subscriptions = relationship("Subscription", back_populates="restaurant", cascade="all, delete-orphan")
    qr_codes = relationship("QRCode", back_populates="restaurant", cascade="all, delete-orphan")
    usage_logs = relationship("UsageLog", back_populates="restaurant", cascade="all, delete-orphan")

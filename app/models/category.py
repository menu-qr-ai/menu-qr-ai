from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)

    restaurant = relationship("Restaurant", back_populates="categories")
    dishes = relationship("Dish", back_populates="category", cascade="all, delete-orphan")

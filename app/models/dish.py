from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Dish(Base):
    __tablename__ = "dishes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    price = Column(Float)
    ingredients = Column(Text)
    allergens = Column(Text)
    image = Column(String)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)

    category = relationship("Category", back_populates="dishes")
    restaurant = relationship("Restaurant", back_populates="dishes")
    translations = relationship("Translation", back_populates="dish", cascade="all, delete-orphan")
    image_generations = relationship("ImageGeneration", back_populates="dish", cascade="all, delete-orphan")

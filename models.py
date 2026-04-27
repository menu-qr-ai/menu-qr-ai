from sqlalchemy import Column, Integer, String, Float, ForeignKey
from database import Base
from sqlalchemy.orm import relationship

# -------------------------
# RESTAURANTE
# -------------------------
class Restaurant(Base):
    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)

    categories = relationship("Category", back_populates="restaurant")


# -------------------------
# CATEGORY
# -------------------------
class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)

    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))

    restaurant = relationship("Restaurant", back_populates="categories")
    dishes = relationship("Dish", back_populates="category")


# -------------------------
# DISH
# -------------------------
class Dish(Base):
    __tablename__ = "dishes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    description = Column(String)
    price = Column(Float)
    allergens = Column(String)
    image = Column(String)

    category_id = Column(Integer, ForeignKey("categories.id"))
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"))

    category = relationship("Category", back_populates="dishes")
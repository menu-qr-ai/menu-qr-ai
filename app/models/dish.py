from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Dish(Base):
    __tablename__ = "dishes"
    __table_args__ = (
        CheckConstraint(
            "price IS NULL OR (price >= 0 AND price <= 9999999999.99)",
            name="ck_dishes_price_range",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    price = Column(Numeric(precision=12, scale=2))
    ingredients = Column(Text)
    allergens = Column(Text)
    image = Column(String)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)

    category = relationship("Category", back_populates="dishes")
    restaurant = relationship("Restaurant", back_populates="dishes")
    translations = relationship("Translation", back_populates="dish", cascade="all, delete-orphan")
    image_generations = relationship("ImageGeneration", back_populates="dish", cascade="all, delete-orphan")
    dish_ingredients = relationship("DishIngredient", back_populates="dish", cascade="all, delete-orphan")
    inventory_insights = relationship("InventoryInsight", back_populates="dish", cascade="all, delete-orphan")
    order_lines = relationship("OrderLine", back_populates="dish")
    kitchen_ticket_lines = relationship("KitchenTicketLine", back_populates="dish")

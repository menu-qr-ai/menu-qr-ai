from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    name = Column(String, nullable=False, index=True)
    unit = Column(String, nullable=False, default="unit")
    current_stock = Column(Float, nullable=False, default=0)
    minimum_stock = Column(Float, nullable=False, default=0)
    ideal_stock = Column(Float, nullable=False, default=0)
    cost = Column(Float, nullable=True)
    supplier = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="inventory_items")
    dish_ingredients = relationship("DishIngredient", back_populates="inventory_item", cascade="all, delete-orphan")
    movements = relationship("InventoryMovement", back_populates="inventory_item", cascade="all, delete-orphan")
    alerts = relationship("InventoryAlert", back_populates="inventory_item", cascade="all, delete-orphan")
    insights = relationship("InventoryInsight", back_populates="inventory_item", cascade="all, delete-orphan")


class DishIngredient(Base):
    __tablename__ = "dish_ingredients"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "dish_id", "inventory_item_id", name="uq_dish_ingredients_recipe_item"),
        CheckConstraint("quantity > 0", name="ck_dish_ingredients_quantity_positive"),
        CheckConstraint("unit IN ('g', 'kg', 'ml', 'l', 'unit')", name="ck_dish_ingredients_unit_allowed"),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False, index=True)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False, index=True)
    quantity = Column(Float, nullable=False)
    unit = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    restaurant = relationship("Restaurant", back_populates="dish_ingredients")
    dish = relationship("Dish", back_populates="dish_ingredients")
    inventory_item = relationship("InventoryItem", back_populates="dish_ingredients")


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inventory_movements_quantity_positive"),
        CheckConstraint(
            "movement_type IN ('IN', 'OUT', 'ADJUSTMENT', 'ADJUSTMENT_POSITIVE', 'ADJUSTMENT_NEGATIVE', 'WASTE', "
            "'PRODUCTION_CONSUME', 'PRODUCTION_OUTPUT')",
            name="ck_inventory_movements_type_allowed",
        ),
        CheckConstraint(
            "loss_category IS NULL OR loss_category IN ('expiration', 'spoilage', 'preparation_error', 'breakage', 'unknown_loss', 'other')",
            name="ck_inventory_movements_loss_category_allowed",
        ),
        CheckConstraint("unit IN ('g', 'kg', 'ml', 'l', 'unit')", name="ck_inventory_movements_unit_allowed"),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=False, index=True)
    movement_type = Column(String, nullable=False, index=True)
    quantity = Column(Float, nullable=False)
    unit = Column(String, nullable=False, default="unit")
    historical_unit_cost = Column(Float, nullable=True)
    historical_total_cost = Column(Float, nullable=True)
    wac_previous_stock = Column(Float, nullable=True)
    wac_previous_unit_cost = Column(Float, nullable=True)
    wac_resulting_unit_cost = Column(Float, nullable=True)
    reason = Column(String, nullable=False, default="manual")
    origin_type = Column(String, nullable=True, index=True)
    origin_id = Column(String, nullable=True)
    reference = Column(String, nullable=True)
    loss_category = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    restaurant = relationship("Restaurant", back_populates="inventory_movements")
    inventory_item = relationship("InventoryItem", back_populates="movements")


class InventoryAlert(Base):
    __tablename__ = "inventory_alerts"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True, index=True)
    severity = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    restaurant = relationship("Restaurant", back_populates="inventory_alerts")
    inventory_item = relationship("InventoryItem", back_populates="alerts")


class InventoryInsight(Base):
    __tablename__ = "inventory_insights"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id"), nullable=False, index=True)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True, index=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=True, index=True)
    insight_type = Column(String, nullable=False, index=True)
    priority = Column(String, nullable=False, default="medium")
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    restaurant = relationship("Restaurant", back_populates="inventory_insights")
    inventory_item = relationship("InventoryItem", back_populates="insights")
    dish = relationship("Dish", back_populates="inventory_insights")

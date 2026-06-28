from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Translation(Base):
    __tablename__ = "translations"

    id = Column(Integer, primary_key=True, index=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), nullable=False, index=True)
    language = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    ingredients = Column(Text)
    allergens = Column(Text)
    provider = Column(String, nullable=False, default="openai")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    dish = relationship("Dish", back_populates="translations")


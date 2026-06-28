from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class ImageGeneration(Base):
    __tablename__ = "image_generations"

    id = Column(Integer, primary_key=True, index=True)
    dish_id = Column(Integer, ForeignKey("dishes.id"), index=True)
    prompt = Column(Text, nullable=False)
    image_url = Column(String)
    provider = Column(String, nullable=False, default="openai")
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    dish = relationship("Dish", back_populates="image_generations")


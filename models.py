from sqlalchemy import Column, Integer, String, Float, ForeignKey
from database import Base

# -------------------------
# CATEGORÍAS
# -------------------------
class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)


# -------------------------
# PLATOS
# -------------------------
class Dish(Base):
    __tablename__ = "dishes"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, index=True)
    description = Column(String)
    price = Column(Float)

    allergens = Column(String)

    category_id = Column(Integer, ForeignKey("categories.id"))

    # 📸 NUEVO: imagen del plato
    image = Column(String, nullable=True)
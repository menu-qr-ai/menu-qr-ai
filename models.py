```python
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Float
from sqlalchemy import ForeignKey

from sqlalchemy.orm import relationship

from database import Base


# -------------------------
# RESTAURANT
# -------------------------
class Restaurant(Base):

    __tablename__ = "restaurants"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    categories = relationship(
        "Category",
        back_populates="restaurant"
    )

    dishes = relationship(
        "Dish",
        back_populates="restaurant"
    )


# -------------------------
# CATEGORY
# -------------------------
class Category(Base):

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    restaurant_id = Column(
        Integer,
        ForeignKey("restaurants.id")
    )

    restaurant = relationship(
        "Restaurant",
        back_populates="categories"
    )

    dishes = relationship(
        "Dish",
        back_populates="category"
    )


# -------------------------
# DISH
# -------------------------
class Dish(Base):

    __tablename__ = "dishes"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)

    description = Column(String)

    price = Column(Float)

    ingredients = Column(String)

    allergens = Column(String)

    image = Column(String)

    category_id = Column(
        Integer,
        ForeignKey("categories.id")
    )

    restaurant_id = Column(
        Integer,
        ForeignKey("restaurants.id")
    )

    category = relationship(
        "Category",
        back_populates="dishes"
    )

    restaurant = relationship(
        "Restaurant",
        back_populates="dishes"
    )
```

from sqlalchemy.orm import Session

from app.models import Category, Dish, Restaurant


def seed_demo_data(db: Session) -> None:
    if db.query(Restaurant).first():
        return

    restaurant = Restaurant(name="Demo Restaurant")
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)

    pizzas = Category(name="Pizzas", restaurant_id=restaurant.id)
    burgers = Category(name="Burgers", restaurant_id=restaurant.id)
    desserts = Category(name="Desserts", restaurant_id=restaurant.id)

    db.add_all([pizzas, burgers, desserts])
    db.commit()
    db.refresh(pizzas)
    db.refresh(burgers)
    db.refresh(desserts)

    db.add_all(
        [
            Dish(
                name="Pizza Margarita",
                description="Classic pizza with tomato and cheese",
                price=9.99,
                ingredients="Tomato, mozzarella, basil",
                allergens="Gluten, lactose",
                image="https://images.unsplash.com/photo-1513104890138-7c749659a591?auto=format&fit=crop&w=900&q=80",
                category_id=pizzas.id,
                restaurant_id=restaurant.id,
            ),
            Dish(
                name="Cheeseburger",
                description="Beef burger with melted cheese",
                price=11.50,
                ingredients="Beef, cheese, lettuce, bun",
                allergens="Gluten, lactose",
                image="https://images.unsplash.com/photo-1568901346375-23c9450c58cd?auto=format&fit=crop&w=900&q=80",
                category_id=burgers.id,
                restaurant_id=restaurant.id,
            ),
            Dish(
                name="Tiramisu",
                description="Italian dessert with coffee and mascarpone",
                price=5.50,
                ingredients="Mascarpone, coffee, cocoa, biscuits",
                allergens="Gluten, lactose, eggs",
                image="https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?auto=format&fit=crop&w=900&q=80",
                category_id=desserts.id,
                restaurant_id=restaurant.id,
            ),
        ]
    )
    db.commit()


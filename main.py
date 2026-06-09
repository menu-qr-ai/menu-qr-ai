```python id="h9cft9"
from fastapi import FastAPI
from fastapi import Request

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import RedirectResponse
from fastapi.responses import StreamingResponse

from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import io
import os
import json
import qrcode

from openai import OpenAI

from database import Base
from database import engine
from database import SessionLocal

from models import Restaurant
from models import Category
from models import Dish


# --------------------------------------------------
# OPENAI
# --------------------------------------------------
client = None

api_key = os.getenv("OPENAI_API_KEY")

if api_key:
    client = OpenAI(api_key=api_key)


# --------------------------------------------------
# APP
# --------------------------------------------------
app = FastAPI()


# --------------------------------------------------
# STATIC
# --------------------------------------------------
app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)

templates = Jinja2Templates(
    directory="templates"
)


# --------------------------------------------------
# CORS
# --------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# DATABASE
# --------------------------------------------------
Base.metadata.create_all(bind=engine)


# --------------------------------------------------
# ROOT
# --------------------------------------------------
@app.get("/")
def root():

    return RedirectResponse(
        url="/menu"
    )


# --------------------------------------------------
# TEST
# --------------------------------------------------
@app.get("/test")
def test():

    return {
        "ok": True
    }


# --------------------------------------------------
# SEED DATA
# --------------------------------------------------
def seed_data():

    db = SessionLocal()

    try:

        restaurant_exists = db.query(
            Restaurant
        ).first()

        if restaurant_exists:
            return

        restaurant = Restaurant(
            name="Demo Restaurant"
        )

        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)

        pizzas = Category(
            name="Pizzas",
            restaurant_id=restaurant.id
        )

        burgers = Category(
            name="Burgers",
            restaurant_id=restaurant.id
        )

        desserts = Category(
            name="Desserts",
            restaurant_id=restaurant.id
        )

        db.add_all([
            pizzas,
            burgers,
            desserts
        ])

        db.commit()

        dish_1 = Dish(
            name="Pizza Margarita",
            description="Classic Italian pizza with mozzarella and tomato",
            price=9.99,
            ingredients="Tomato, mozzarella, basil",
            allergens="Gluten, lactose",
            image="https://images.unsplash.com/photo-1513104890138-7c749659a591",
            category_id=pizzas.id,
            restaurant_id=restaurant.id
        )

        dish_2 = Dish(
            name="Cheeseburger",
            description="Beef burger with cheddar cheese",
            price=11.50,
            ingredients="Beef, cheddar, bread",
            allergens="Gluten, lactose",
            image="https://images.unsplash.com/photo-1568901346375-23c9450c58cd",
            category_id=burgers.id,
            restaurant_id=restaurant.id
        )

        dish_3 = Dish(
            name="Tiramisu",
            description="Traditional Italian dessert",
            price=5.50,
            ingredients="Mascarpone, coffee, cacao",
            allergens="Gluten, lactose",
            image="https://images.unsplash.com/photo-1571877227200-a0d98ea607e9",
            category_id=desserts.id,
            restaurant_id=restaurant.id
        )

        db.add_all([
            dish_1,
            dish_2,
            dish_3
        ])

        db.commit()

    finally:
        db.close()


@app.on_event("startup")
def startup():

    seed_data()


# --------------------------------------------------
# QR GENERATOR
# --------------------------------------------------
@app.get("/qr/{restaurant_id}/{table_id}")
def generate_qr(
    restaurant_id: int,
    table_id: int
):

    url = (
        f"https://menu-qr-ai-1.onrender.com"
        f"/menu?restaurant_id={restaurant_id}"
        f"&table={table_id}"
    )

    img = qrcode.make(url)

    buffer = io.BytesIO()

    img.save(buffer)

    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="image/png"
    )


# --------------------------------------------------
# MENU
# --------------------------------------------------
@app.get("/menu")
def menu(
    request: Request,
    restaurant_id: int = 1
):

    db = SessionLocal()

    try:

        categories = db.query(
            Category
        ).filter(
            Category.restaurant_id == restaurant_id
        ).all()

        dishes = db.query(
            Dish
        ).filter(
            Dish.restaurant_id == restaurant_id
        ).all()

        categories_json = json.dumps([
            {
                "id": category.id,
                "name": category.name
            }
            for category in categories
        ])

        dishes_json = json.dumps([
            {
                "id": dish.id,
                "name": dish.name,
                "description": dish.description,
                "price": dish.price,
                "ingredients": dish.ingredients,
                "allergens": dish.allergens,
                "image": dish.image,
                "category_id": dish.category_id
            }
            for dish in dishes
        ])

        return templates.TemplateResponse(
            "menu.html",
            {
                "request": request,
                "categories": categories_json,
                "dishes": dishes_json
            }
        )

    finally:
        db.close()


# --------------------------------------------------
# AI TRANSLATION
# --------------------------------------------------
@app.get("/ai/translate-dish/{dish_id}")
def translate_dish(
    dish_id: int,
    lang: str = "en"
):

    if client is None:

        return {
            "error": "OPENAI_API_KEY not configured"
        }

    db = SessionLocal()

    try:

        dish = db.query(
            Dish
        ).filter(
            Dish.id == dish_id
        ).first()

        if not dish:

            return {
                "error": "Dish not found"
            }

        prompt = f"""
        Translate this restaurant dish to {lang}.

        Return ONLY valid JSON.

        {{
            "name": "...",
            "description": "...",
            "ingredients": "...",
            "allergens": "..."
        }}

        Name: {dish.name}

        Description: {dish.description}

        Ingredients: {dish.ingredients}

        Allergens: {dish.allergens}
        """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional restaurant translator."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        content = response.choices[0].message.content

        try:

            return json.loads(content)

        except:

            return {
                "error": "Invalid JSON response",
                "raw": content
            }

    finally:
        db.close()
```

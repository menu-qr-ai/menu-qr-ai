from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from fastapi.templating import Jinja2Templates
from fastapi import Request

import os
import io
import json
import qrcode

from database import engine, Base, SessionLocal
from models import Restaurant, Category, Dish

from openai import OpenAI

# -------------------------
# OPENAI
# -------------------------
client = None

api_key = os.getenv("OPENAI_API_KEY")

if api_key:
    client = OpenAI(api_key=api_key)

# -------------------------
# APP
# -------------------------
app = FastAPI()

# -------------------------
# STATIC + TEMPLATES
# -------------------------
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# -------------------------
# CORS
# -------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# DB INIT
# -------------------------
Base.metadata.create_all(bind=engine)

# -------------------------
# ROOT
# -------------------------
@app.get("/")
def root():
    return RedirectResponse(url="/menu")

# -------------------------
# SEED DATA
# -------------------------
def seed_data():

    db = SessionLocal()

    try:

        if db.query(Restaurant).first():
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

        postres = Category(
            name="Postres",
            restaurant_id=restaurant.id
        )

        db.add_all([pizzas, postres])
        db.commit()

        pizza = Dish(
            name="Pizza Margarita",
            description="Tomate y mozzarella",
            price=9.99,
            allergens="gluten, lactosa",
            ingredients="tomate, mozzarella, albahaca",
            image="https://images.unsplash.com/photo-1513104890138-7c749659a591",
            category_id=1,
            restaurant_id=restaurant.id
        )

        tiramisu = Dish(
            name="Tiramisú",
            description="Postre italiano clásico",
            price=5.50,
            allergens="gluten, lactosa",
            ingredients="mascarpone, cacao, café",
            image="https://images.unsplash.com/photo-1571877227200-a0d98ea607e9",
            category_id=2,
            restaurant_id=restaurant.id
        )

        db.add_all([pizza, tiramisu])
        db.commit()

    finally:
        db.close()

@app.on_event("startup")
def startup():
    seed_data()

# -------------------------
# QR
# -------------------------
@app.get("/qr/{restaurant_id}/{table_id}")
def generate_qr(
    restaurant_id: int,
    table_id: int
):

    url = (
        f"https://menu-qr-ai-1.onrender.com/"
        f"menu?restaurant_id={restaurant_id}"
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

# -------------------------
# MENU
# -------------------------
@app.get("/menu")
def menu(
    request: Request,
    restaurant_id: int = 1,
    table: int = 0,
    lang: str | None = None
):

    # -------------------------
    # AUTO LANGUAGE DETECTION
    # -------------------------

    if lang is None:

        browser_lang = request.headers.get(
            "accept-language",
            "es"
        ).lower()

        if browser_lang.startswith("en"):
            lang = "en"

        elif browser_lang.startswith("fr"):
            lang = "fr"

        elif browser_lang.startswith("de"):
            lang = "de"

        elif browser_lang.startswith("it"):
            lang = "it"

        else:
            lang = "es"

    db = SessionLocal()

    try:

        categories = db.query(Category).filter(
            Category.restaurant_id == restaurant_id
        ).all()

        dishes = db.query(Dish).filter(
            Dish.restaurant_id == restaurant_id
        ).all()

        categories_json = json.dumps([
            {
                "id": c.id,
                "name": c.name
            }
            for c in categories
        ])

        dishes_json = json.dumps([
            {
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "price": d.price,
                "allergens": d.allergens,
                "ingredients": d.ingredients,
                "image": d.image,
                "category_id": d.category_id
            }
            for d in dishes
        ])

        return templates.TemplateResponse(
            "menu.html",
            {
                "request": request,
                "restaurant_id": restaurant_id,
                "table": table,
                "lang": lang,
                "categories": categories_json,
                "dishes": dishes_json
            }
        )

    finally:
        db.close()
        # force rebuild
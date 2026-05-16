from fastapi import FastAPI, Query, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
import os
import io
import qrcode

from database import engine, Base, SessionLocal
from models import Restaurant, Category, Dish

from openai import OpenAI

# -------------------------
# OPENAI (opcional)
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
# ROOT
# -------------------------
@app.get("/")
def root():
    return RedirectResponse(url="/menu")

# -------------------------
# DB INIT
# -------------------------
Base.metadata.create_all(bind=engine)

# -------------------------
# SEED DATA
# -------------------------
def seed_data():

    db = SessionLocal()

    try:

        if db.query(Restaurant).first():
            return

        r1 = Restaurant(name="Demo Restaurant")
        db.add(r1)
        db.commit()
        db.refresh(r1)

        entrantes = Category(name="Entrantes", restaurant_id=r1.id)
        pizzas = Category(name="Pizzas", restaurant_id=r1.id)
        postres = Category(name="Postres", restaurant_id=r1.id)

        db.add_all([entrantes, pizzas, postres])
        db.commit()

        d1 = Dish(
            name="Pizza Margarita",
            description="Tomate, mozzarella y albahaca",
            price=9.99,
            allergens="gluten, lactosa",
            ingredients="tomate, mozzarella, albahaca",
            category_id=pizzas.id,
            restaurant_id=r1.id,
            image="https://images.unsplash.com/photo-1513104890138-7c749659a591"
        )

        d2 = Dish(
            name="Tiramisú",
            description="Postre italiano clásico",
            price=5.50,
            allergens="lactosa, gluten",
            ingredients="mascarpone, café, cacao",
            category_id=postres.id,
            restaurant_id=r1.id,
            image="https://images.unsplash.com/photo-1571877227200-a0d98ea607e9"
        )

        db.add_all([d1, d2])
        db.commit()

    finally:
        db.close()

# -------------------------
# STARTUP
# -------------------------
@app.on_event("startup")
def startup():
    try:
        seed_data()
    except Exception as e:
        print("Seed error:", e)

# -------------------------
# CATEGORIES
# -------------------------
@app.get("/categories")
def get_categories():
    db = SessionLocal()
    try:
        return db.query(Category).all()
    finally:
        db.close()

# -------------------------
# DISHES
# -------------------------
@app.get("/dishes")
def get_dishes():
    db = SessionLocal()
    try:
        return db.query(Dish).all()
    finally:
        db.close()

# -------------------------
# CREATE DISH
# -------------------------
@app.post("/dishes")
def create_dish(data: dict):

    db = SessionLocal()

    try:

        dish = Dish(
            name=data["name"],
            description=data["description"],
            price=data["price"],
            allergens=data.get("allergens", ""),
            ingredients=data.get("ingredients", ""),
            image=data.get("image", ""),
            category_id=data["category_id"],
            restaurant_id=data["restaurant_id"]
        )

        db.add(dish)
        db.commit()
        db.refresh(dish)

        return dish

    finally:
        db.close()

# -------------------------
# UPDATE DISH
# -------------------------
@app.put("/dishes/{dish_id}")
def update_dish(dish_id: int, data: dict):

    db = SessionLocal()

    try:

        dish = db.query(Dish).filter(Dish.id == dish_id).first()

        if not dish:
            raise HTTPException(status_code=404, detail="Dish not found")

        dish.name = data.get("name", dish.name)
        dish.description = data.get("description", dish.description)
        dish.price = data.get("price", dish.price)
        dish.allergens = data.get("allergens", dish.allergens)
        dish.ingredients = data.get("ingredients", dish.ingredients)
        dish.image = data.get("image", dish.image)

        db.commit()
        db.refresh(dish)

        return dish

    finally:
        db.close()

# -------------------------
# DELETE DISH
# -------------------------
@app.delete("/dishes/{dish_id}")
def delete_dish(dish_id: int):

    db = SessionLocal()

    try:

        dish = db.query(Dish).filter(Dish.id == dish_id).first()

        if not dish:
            raise HTTPException(status_code=404, detail="Dish not found")

        db.delete(dish)
        db.commit()

        return {"message": "Dish deleted"}

    finally:
        db.close()

# -------------------------
# QR POR MESA
# -------------------------
@app.get("/qr/{table_id}")
def generate_qr(table_id: int):

    url = f"https://menu-qr-ai-1.onrender.com/menu?table={table_id}"

    img = qrcode.make(url)

    buffer = io.BytesIO()
    img.save(buffer)
    buffer.seek(0)

    return StreamingResponse(buffer, media_type="image/png")

# -------------------------
# IA RECOMENDACIÓN
# -------------------------
@app.get("/ai-recommendation")
def ai_recommendation(question: str = Query(...)):

    if client is None:
        return {"error": "OPENAI_API_KEY no configurada"}

    db = SessionLocal()
    dishes = db.query(Dish).all()
    db.close()

    menu_text = "\n".join([
        f"{d.name} - {d.description} - {d.price}€"
        for d in dishes
    ])

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Eres un camarero experto."},
            {"role": "user", "content": f"MENU:\n{menu_text}\n\nCLIENTE:\n{question}"}
        ]
    )

    return {"answer": response.choices[0].message.content}

# -------------------------
# IA TRADUCCIÓN PLATO (PASO 2 QUE ESTÁS HACIENDO)
# -------------------------
@app.get("/ai-translate-dish/{dish_id}")
def translate_dish(dish_id: int, lang: str = "en"):

    db = SessionLocal()
    dish = db.query(Dish).filter(Dish.id == dish_id).first()
    db.close()

    if not dish:
        return {"error": "Dish not found"}

    prompt = f"""
    Traduce este plato a {lang}:

    Nombre: {dish.name}
    Descripción: {dish.description}
    Ingredientes: {dish.ingredients}
    Alérgenos: {dish.allergens}

    Devuelve traducción natural para restaurante.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Eres traductor gastronómico profesional."},
            {"role": "user", "content": prompt}
        ]
    )

    return {
        "translation": response.choices[0].message.content
    }

# -------------------------
# MENU
# -------------------------
@app.get("/menu", response_class=HTMLResponse)
def menu(table: int | None = None):

    table_value = table if table else "Sin asignar"

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Menu</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">

        <style>
            body {{
                margin: 0;
                font-family: system-ui;
                background: #0e0f12;
                color: white;
            }}

            header {{
                text-align: center;
                padding: 30px;
            }}

            .table {{
                opacity: 0.7;
                font-size: 14px;
                margin-top: 5px;
            }}

            #menu {{
                max-width: 700px;
                margin: auto;
                padding: 20px;
            }}

            .card {{
                background: #171922;
                margin-bottom: 16px;
                border-radius: 16px;
                overflow: hidden;
                border: 1px solid #2a2d39;
            }}

            .card img {{
                width: 100%;
                height: 220px;
                object-fit: cover;
            }}

            .content {{
                padding: 16px;
            }}

            h2 {{
                margin-top: 40px;
            }}

            p {{
                color: #b8bcc8;
            }}
        </style>
    </head>

    <body>

        <header>
            <h1>🍽️ Restaurante Digital</h1>
            <div class="table">Mesa: {table_value}</div>
        </header>

        <div id="menu">Cargando...</div>

        <script>
        async function load() {{

            const cats = await fetch("/categories").then(r => r.json());
            const dishes = await fetch("/dishes").then(r => r.json());

            let html = "";

            cats.forEach(c => {{

                html += `<h2>${{c.name}}</h2>`;

                dishes
                    .filter(d => d.category_id === c.id)
                    .forEach(d => {{

                        html += `
                        <div class="card">
                            <img src="${{d.image}}">
                            <div class="content">
                                <h3>${{d.name}}</h3>
                                <p>${{d.description}}</p>
                                <b>${{d.price}}€</b>
                            </div>
                        </div>
                        `;
                    }});
            }});

            document.getElementById("menu").innerHTML = html;
        }}

        load();
        </script>

    </body>
    </html>
    """
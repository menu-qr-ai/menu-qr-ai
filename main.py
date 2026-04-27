from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

import os

from database import engine, Base, SessionLocal
from models import Restaurant, Category, Dish

# -------------------------
# OPENAI (opcional / seguro)
# -------------------------
from openai import OpenAI

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

    if db.query(Restaurant).first():
        db.close()
        return

    # RESTAURANTE DEMO
    r1 = Restaurant(name="Demo Restaurant")

    db.add(r1)
    db.commit()

    # CATEGORÍAS
    entrantes = Category(name="Entrantes", restaurant_id=r1.id)
    pizzas = Category(name="Pizzas", restaurant_id=r1.id)
    postres = Category(name="Postres", restaurant_id=r1.id)

    db.add_all([entrantes, pizzas, postres])
    db.commit()

    # PLATOS
    d1 = Dish(
        name="Pizza Margarita",
        description="Tomate, mozzarella y albahaca",
        price=9.99,
        allergens="gluten, lactosa",
        category_id=pizzas.id,
        restaurant_id=r1.id,
        image="https://images.unsplash.com/photo-1601924582970-9238bcb495d4"
    )

    d2 = Dish(
        name="Tiramisú",
        description="Postre italiano clásico",
        price=5.50,
        allergens="lactosa, gluten",
        category_id=postres.id,
        restaurant_id=r1.id,
        image="https://images.unsplash.com/photo-1571877227200-a0d98ea607e9"
    )

    db.add_all([d1, d2])
    db.commit()
    db.close()

# 🔥 ARRANQUE SEGURO EN RENDER
@app.on_event("startup")
def startup():
    seed_data()

# -------------------------
# CATEGORIES
# -------------------------
@app.get("/categories")
def get_categories():
    db = SessionLocal()
    data = db.query(Category).all()
    db.close()
    return data

@app.post("/categories")
def create_category(name: str):
    db = SessionLocal()
    c = Category(name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    db.close()
    return c

# -------------------------
# DISHES
# -------------------------
@app.get("/dishes")
def get_dishes():
    db = SessionLocal()
    data = db.query(Dish).all()
    db.close()
    return data

@app.post("/dishes")
def create_dish(
    name: str,
    description: str,
    price: float,
    allergens: str,
    category_id: int = None,
    image: str = None
):
    db = SessionLocal()

    d = Dish(
        name=name,
        description=description,
        price=price,
        allergens=allergens,
        category_id=category_id,
        image=image
    )

    db.add(d)
    db.commit()
    db.refresh(d)
    db.close()
    return d

# -------------------------
# IA (SAFE)
# -------------------------
@app.get("/ai-recommendation")
def ai_recommendation(question: str = Query(...)):

    if client is None:
        return {"error": "IA no configurada (falta OPENAI_API_KEY en Render)"}

    db = SessionLocal()
    dishes = db.query(Dish).all()
    db.close()

    menu_text = "\n".join([
        f"{d.name} - {d.description} - {d.price}€ - {d.allergens}"
        for d in dishes
    ])

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "Eres un camarero experto. Recomienda platos del menú."
            },
            {
                "role": "user",
                "content": f"""
MENÚ:
{menu_text}

CLIENTE:
{question}

Recomienda platos concretos del menú.
"""
            }
        ]
    )

    return {
        "answer": response.choices[0].message.content
    }

# -------------------------
# MENU HTML (UI BASE PRO)
# -------------------------
@app.get("/menu", response_class=HTMLResponse)
def menu():

    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Menú</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">

        <style>
            body {
                margin: 0;
                font-family: system-ui, -apple-system, sans-serif;
                background: #0e0f12;
                color: #f2f2f2;
            }

            header {
                padding: 28px 16px 14px;
                text-align: center;
            }

            header h1 {
                margin: 0;
                font-size: 22px;
                font-weight: 800;
            }

            header p {
                margin: 6px 0 0;
                font-size: 13px;
                color: #a9a9a9;
            }

            #menu {
                max-width: 720px;
                margin: auto;
                padding: 16px;
            }

            .category {
                margin-top: 26px;
            }

            .category-title {
                font-size: 15px;
                font-weight: 700;
                margin-bottom: 12px;
                border-left: 3px solid #ff5a5f;
                padding-left: 10px;
            }

            .card {
                background: #171922;
                border-radius: 14px;
                overflow: hidden;
                margin-bottom: 12px;
            }

            .card img {
                width: 100%;
                height: 160px;
                object-fit: cover;
            }

            .content {
                padding: 12px;
            }

            .title {
                font-size: 15px;
                font-weight: 700;
            }

            .desc {
                font-size: 12px;
                color: #a9a9a9;
                margin-top: 4px;
            }

            .bottom {
                display: flex;
                justify-content: space-between;
                margin-top: 8px;
            }

            .price {
                color: #4ade80;
                font-weight: 700;
            }

            .badge {
                font-size: 10px;
                color: #ff5a5f;
            }
        </style>
    </head>

    <body>

    <header>
        <h1>🍽️ Restaurante Digital</h1>
        <p>Elige, disfruta y repite</p>
    </header>

    <div id="menu">Cargando menú...</div>

    <script>
    async function load() {

        const cats = await fetch("/categories").then(r => r.json());
        const dishes = await fetch("/dishes").then(r => r.json());

        const menu = document.getElementById("menu");
        menu.innerHTML = "";

        cats.forEach(cat => {

            const section = document.createElement("div");
            section.className = "category";

            let html = `<div class="category-title">${cat.name}</div>`;

            dishes
                .filter(d => d.category_id === cat.id)
                .forEach(d => {

                    html += `
                        <div class="card">
                            <img src="${d.image}">
                            <div class="content">
                                <div class="title">${d.name}</div>
                                <div class="desc">${d.description}</div>
                                <div class="bottom">
                                    <div class="price">${d.price} €</div>
                                    <div class="badge">${d.allergens || ''}</div>
                                </div>
                            </div>
                        </div>
                    `;
                });

            section.innerHTML = html;
            menu.appendChild(section);
        });
    }

    load();
    </script>

    </body>
    </html>
    """
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

import os

from database import engine, Base, SessionLocal
from models import Category, Dish

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

    if db.query(Category).first():
        db.close()
        return

    entrantes = Category(name="Entrantes")
    pizzas = Category(name="Pizzas")
    postres = Category(name="Postres")

    db.add_all([entrantes, pizzas, postres])
    db.commit()

    # IMPORTANTE: refrescar IDs
    db.refresh(entrantes)
    db.refresh(pizzas)
    db.refresh(postres)

    d1 = Dish(
        name="Pizza Margarita",
        description="Tomate, mozzarella y albahaca",
        price=9.99,
        allergens="gluten, lactosa",
        category_id=pizzas.id,
        image="https://images.unsplash.com/photo-1601924582970-9238bcb495d4"
    )

    d2 = Dish(
        name="Tiramisú",
        description="Postre italiano clásico",
        price=5.50,
        allergens="lactosa, gluten",
        category_id=postres.id,
        image="https://images.unsplash.com/photo-1571877227200-a0d98ea607e9"
    )

    db.add_all([d1, d2])
    db.commit()
    db.close()

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
# IA (segura)
# -------------------------
@app.get("/ai-recommendation")
def ai_recommendation(question: str = Query(...)):

    if client is None:
        return {
            "error": "IA no configurada (falta OPENAI_API_KEY en Render)"
        }

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
# MENU (BASE SIMPLE - PRONTO UI NUEVO)
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
            :root {
                --bg: #0e0f12;
                --card: #171922;
                --text: #f2f2f2;
                --muted: #a9a9a9;
                --accent: #ff5a5f;
                --price: #4ade80;
            }

            body {
                margin: 0;
                font-family: system-ui, -apple-system, sans-serif;
                background: var(--bg);
                color: var(--text);
            }

            header {
                padding: 28px 16px 14px;
                text-align: center;
            }

            header h1 {
                margin: 0;
                font-size: 22px;
                font-weight: 800;
                letter-spacing: 0.5px;
            }

            header p {
                margin: 6px 0 0;
                font-size: 13px;
                color: var(--muted);
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
                color: var(--text);
                border-left: 3px solid var(--accent);
                padding-left: 10px;
                opacity: 0.9;
            }

            .card {
                background: var(--card);
                border-radius: 14px;
                overflow: hidden;
                margin-bottom: 12px;
                box-shadow: 0 8px 20px rgba(0,0,0,0.35);
                transition: transform 0.15s ease;
            }

            .card:active {
                transform: scale(0.98);
            }

            .card img {
                width: 100%;
                height: 160px;
                object-fit: cover;
                filter: contrast(1.05) saturate(1.1);
            }

            .content {
                padding: 12px;
            }

            .title {
                font-size: 15px;
                font-weight: 700;
                margin: 0 0 4px;
            }

            .desc {
                font-size: 12px;
                color: var(--muted);
                line-height: 1.4;
                margin-bottom: 10px;
            }

            .bottom {
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .price {
                font-weight: 700;
                color: var(--price);
                font-size: 13px;
            }

            .badge {
                font-size: 10px;
                background: rgba(255,90,95,0.12);
                color: var(--accent);
                padding: 4px 8px;
                border-radius: 999px;
            }

            footer {
                text-align: center;
                padding: 22px;
                font-size: 11px;
                color: #666;
            }
        </style>
    </head>

    <body>

    <header>
        <h1>🍽️ Restaurante Digital</h1>
        <p>Elige, disfruta y repite</p>
    </header>

    <div id="menu">Cargando menú...</div>

    <footer>Hecho con FastAPI 🚀</footer>

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
                            <img src="${d.image || 'https://images.unsplash.com/photo-1540189549336-e6e99c3679fe'}">

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
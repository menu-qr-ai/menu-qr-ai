from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

import os

from database import engine, Base, SessionLocal
from models import Category, Dish

# -------------------------
# OPENAI (seguro)
# -------------------------
from openai import OpenAI

client = None
if os.getenv("OPENAI_API_KEY"):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
# ROOT → REDIRECT
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

    d1 = Dish(
        name="Pizza Margarita",
        description="Tomate, mozzarella y albahaca",
        price=9.99,
        allergens="gluten, lactosa",
        category_id=entrantes.id,
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
# 🤖 IA (SAFE)
# -------------------------
@app.get("/ai-recommendation")
def ai_recommendation(question: str = Query(...)):

    if client is None:
        return {"error": "OPENAI_API_KEY no configurada en Render"}

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

Recomienda platos concretos.
"""
            }
        ]
    )

    return {
        "answer": response.choices[0].message.content
    }

# -------------------------
# 🌐 MENU HTML
# -------------------------
@app.get("/menu", response_class=HTMLResponse)
def menu():

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Menú</title>
    </head>
    <body>
        <h1>🍽️ Menú del Restaurante</h1>
        <div id="menu">Cargando...</div>

        <script>
        async function load() {
            const cats = await fetch("/categories").then(r => r.json());
            const dishes = await fetch("/dishes").then(r => r.json());

            let html = "";

            cats.forEach(c => {
                html += "<h2>" + c.name + "</h2>";

                dishes.filter(d => d.category_id === c.id).forEach(d => {
                    html += `
                        <div>
                            <h3>${d.name}</h3>
                            <p>${d.description}</p>
                            <b>${d.price}€</b>
                        </div>
                    `;
                });
            });

            document.getElementById("menu").innerHTML = html;
        }

        load();
        </script>
    </body>
    </html>
    """
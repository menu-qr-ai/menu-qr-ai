from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from database import engine, Base, SessionLocal
import models
from models import Category, Dish

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
# DB INIT
# -------------------------
Base.metadata.create_all(bind=engine)

# -------------------------
# SEED (datos base automáticos)
# -------------------------
def seed_data():
    db = SessionLocal()

    # si ya hay datos, no duplicar
    if db.query(Category).first():
        db.close()
        return

    # categorías base
    entrantes = Category(name="Entrantes")
    pizzas = Category(name="Pizzas")
    postres = Category(name="Postres")

    db.add_all([entrantes, pizzas, postres])
    db.commit()

    # platos base
    d1 = Dish(
        name="Pizza Margarita",
        description="Tomate, mozzarella y albahaca",
        price=9.99,
        allergens="gluten, lactosa",
        category_id=2,
        image="https://images.unsplash.com/photo-1601924582970-9238bcb495d4"
    )

    d2 = Dish(
        name="Tiramisú",
        description="Postre italiano clásico",
        price=5.50,
        allergens="lactosa, gluten",
        category_id=3,
        image="https://images.unsplash.com/photo-1571877227200-a0d98ea607e9"
    )

    db.add_all([d1, d2])
    db.commit()
    db.close()

# ejecutar seed al arrancar
seed_data()

# -------------------------
# CATEGORIES
# -------------------------
@app.post("/categories")
def create_category(name: str):
    db = SessionLocal()
    category = Category(name=name)
    db.add(category)
    db.commit()
    db.refresh(category)
    db.close()
    return category


@app.get("/categories")
def get_categories():
    db = SessionLocal()
    data = db.query(Category).all()
    db.close()
    return data

# -------------------------
# DISHES
# -------------------------
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

    dish = Dish(
        name=name,
        description=description,
        price=price,
        allergens=allergens,
        category_id=category_id,
        image=image
    )

    db.add(dish)
    db.commit()
    db.refresh(dish)
    db.close()
    return dish


@app.get("/dishes")
def get_dishes():
    db = SessionLocal()
    data = db.query(Dish).all()
    db.close()
    return data

# -------------------------
# 🌐 MENÚ PÚBLICO (QR READY)
# -------------------------
@app.get("/menu", response_class=HTMLResponse)
def public_menu():

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Menú Restaurante</title>

        <style>
            body {
                font-family: system-ui;
                background: #f4f5f7;
                margin: 0;
                padding: 0;
            }

            h1 {
                text-align: center;
                padding: 18px;
                background: white;
                margin: 0;
                box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            }

            #menu {
                max-width: 500px;
                margin: auto;
                padding: 15px;
            }

            .category-title {
                font-size: 18px;
                font-weight: bold;
                border-left: 4px solid #ff4d4d;
                padding-left: 10px;
                margin: 20px 0 10px;
            }

            .card {
                background: white;
                border-radius: 16px;
                padding: 12px;
                margin-bottom: 12px;
                box-shadow: 0 4px 14px rgba(0,0,0,0.06);
            }

            img {
                width: 100%;
                border-radius: 12px;
                margin-bottom: 8px;
            }

            .price {
                font-weight: bold;
                color: green;
            }
        </style>
    </head>

    <body>

    <h1>🍽️ Menú del Restaurante</h1>

    <div id="menu">Cargando...</div>

    <script>
    async function loadMenu() {

        const resCats = await fetch("/categories");
        const categories = await resCats.json();

        const resDishes = await fetch("/dishes");
        const dishes = await resDishes.json();

        const menu = document.getElementById("menu");
        menu.innerHTML = "";

        categories.forEach(cat => {

            const section = document.createElement("div");

            section.innerHTML = `<div class="category-title">${cat.name}</div>`;

            dishes
                .filter(d => Number(d.category_id) === Number(cat.id))
                .forEach(d => {

                    section.innerHTML += `
                        <div class="card">
                            <img src="${d.image || 'https://via.placeholder.com/400x200'}">
                            <h3>${d.name}</h3>
                            <p>${d.description}</p>
                            <div class="price">${d.price} €</div>
                            <small>⚠️ ${d.allergens}</small>
                        </div>
                    `;
                });

            menu.appendChild(section);
        });
    }

    loadMenu();
    </script>

    </body>
    </html>
    """
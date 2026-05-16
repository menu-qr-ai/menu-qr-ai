from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
import os

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
        # evitar duplicados
        existing_restaurant = db.query(Restaurant).first()

        if existing_restaurant:
            return

        r1 = Restaurant(name="Demo Restaurant")
        db.add(r1)
        db.commit()
        db.refresh(r1)

        entrantes = Category(
            name="Entrantes",
            restaurant_id=r1.id
        )

        pizzas = Category(
            name="Pizzas",
            restaurant_id=r1.id
        )

        postres = Category(
            name="Postres",
            restaurant_id=r1.id
        )

        db.add_all([entrantes, pizzas, postres])
        db.commit()

        db.refresh(entrantes)
        db.refresh(pizzas)
        db.refresh(postres)

        d1 = Dish(
            name="Pizza Margarita",
            description="Tomate, mozzarella y albahaca",
            price=9.99,
            allergens="gluten, lactosa",
            category_id=pizzas.id,
            restaurant_id=r1.id,
            image="https://images.unsplash.com/photo-1513104890138-7c749659a591?q=80&w=1200&auto=format&fit=crop"
        )

        d2 = Dish(
            name="Tiramisú",
            description="Postre italiano clásico",
            price=5.50,
            allergens="lactosa, gluten",
            category_id=postres.id,
            restaurant_id=r1.id,
            image="https://images.unsplash.com/photo-1571877227200-a0d98ea607e9?q=80&w=1200&auto=format&fit=crop"
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
# GET DISHES
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
            raise HTTPException(
                status_code=404,
                detail="Dish not found"
            )

        dish.name = data.get("name", dish.name)
        dish.description = data.get(
            "description",
            dish.description
        )

        dish.price = data.get("price", dish.price)

        dish.allergens = data.get(
            "allergens",
            dish.allergens
        )

        dish.image = data.get(
            "image",
            dish.image
        )

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
        dish = db.query(Dish).filter(
            Dish.id == dish_id
        ).first()

        if not dish:
            raise HTTPException(
                status_code=404,
                detail="Dish not found"
            )

        db.delete(dish)
        db.commit()

        return {
            "message": "Dish deleted"
        }

    finally:
        db.close()

# -------------------------
# IA
# -------------------------
@app.get("/ai-recommendation")
def ai_recommendation(question: str = Query(...)):

    if client is None:
        return {
            "error": "OPENAI_API_KEY no configurada"
        }

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
            {
                "role": "system",
                "content": "Eres un camarero experto. Recomienda platos del menú."
            },
            {
                "role": "user",
                "content": f"MENU:\n{menu_text}\n\nCLIENTE:\n{question}"
            }
        ]
    )

    return {
        "answer": response.choices[0].message.content
    }

# -------------------------
# MENU
# -------------------------
@app.get("/menu", response_class=HTMLResponse)
def menu():

    return """
    <!DOCTYPE html>
    <html lang="es">

    <head>
        <meta charset="UTF-8">

        <title>Menu</title>

        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >

        <style>

            body {
                margin: 0;
                font-family: system-ui;
                background: #0e0f12;
                color: white;
            }

            header {
                text-align: center;
                padding: 30px;
            }

            #menu {
                max-width: 700px;
                margin: auto;
                padding: 20px;
            }

            .card {
                background: #171922;
                margin-bottom: 16px;
                border-radius: 16px;
                overflow: hidden;
                border: 1px solid #2a2d39;
            }

            .card img {
                width: 100%;
                height: 220px;
                object-fit: cover;
                display: block;
                background: #222;
            }

            .content {
                padding: 16px;
            }

            h2 {
                margin-top: 40px;
            }

            p {
                color: #b8bcc8;
            }

        </style>
    </head>

    <body>

        <header>
            <h1>🍽️ Restaurante Digital</h1>
        </header>

        <div id="menu">
            Cargando...
        </div>

        <script>

        async function load() {

            const cats = await fetch("/categories")
                .then(r => r.json());

            const dishes = await fetch("/dishes")
                .then(r => r.json());

            let html = "";

            cats.forEach(c => {

                html += `<h2>${c.name}</h2>`;

                dishes
                    .filter(d => d.category_id === c.id)
                    .forEach(d => {

                        html += `
                            <div class="card">

                                <img
                                    src="${d.image || 'https://via.placeholder.com/800x400?text=Sin+imagen'}"
                                    onerror="this.src='https://via.placeholder.com/800x400?text=Imagen+no+disponible'"
                                >

                                <div class="content">

                                    <h3>${d.name}</h3>

                                    <p>${d.description}</p>

                                    <b>${d.price}€</b>

                                </div>

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
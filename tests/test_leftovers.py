import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.core.rate_limit import SlidingWindowRateLimiter
from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import Category, Dish, DishIngredient, InventoryItem, InventoryMovement, Restaurant, RestaurantMembership, User
from app.routers import inventory as inventory_router
from app.services.leftovers_service import openai_service

ROLE_BY_USER = {1: "owner", 2: "manager", 3: "waiter", 4: "cook", 6: "owner"}


class LeftoversTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(f"sqlite:///{cls.temp_dir.name}/leftovers.db", connect_args={"check_same_thread": False})
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        with cls.SessionTesting() as db:
            db.add_all([Restaurant(id=1, name="Centro", slug="leftovers-centro", vat_percentage=10), Restaurant(id=2, name="Playa", slug="leftovers-playa")])
            for user_id, role in ROLE_BY_USER.items():
                restaurant_id = 1 if user_id < 6 else 2
                db.add(User(id=user_id, email=f"leftovers-{user_id}@hostai.test", hashed_password="x", role=role, restaurant_id=restaurant_id))
                db.flush()
                db.add(RestaurantMembership(user_id=user_id, restaurant_id=restaurant_id, role=role, is_active=True, created_by_user_id=user_id))
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.temp_dir.cleanup()

    def setUp(self):
        def override_get_db():
            db = self.SessionTesting()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        inventory_router.leftover_ideas_rate_limiter.reset()
        with self.SessionTesting() as db:
            for model in (InventoryMovement, DishIngredient, InventoryItem, Dish, Category):
                db.execute(delete(model))
            db.commit()
            category = Category(restaurant_id=1, name="Postres")
            db.add(category)
            db.flush()
            tiramisu = Dish(restaurant_id=1, category_id=category.id, name="Tiramisú", price=6.6)
            old_dish = Dish(restaurant_id=1, category_id=category.id, name="Panna cotta", price=5, is_active=False)
            db.add_all([tiramisu, old_dish])
            items = {
                "Mascarpone": InventoryItem(restaurant_id=1, name="Mascarpone", unit="kg", current_stock=7, ideal_stock=4, cost=8),
                "Nata": InventoryItem(restaurant_id=1, name="Nata", unit="l", current_stock=3, ideal_stock=5, cost=2),
                "Fresas": InventoryItem(restaurant_id=1, name="Fresas", unit="kg", current_stock=2, ideal_stock=3, cost=4),
                "Azafrán": InventoryItem(restaurant_id=1, name="Azafrán", unit="g", current_stock=5, ideal_stock=10, cost=6),
                "Café": InventoryItem(restaurant_id=1, name="Café", unit="kg", current_stock=1, ideal_stock=2, cost=11),
                "Vacío": InventoryItem(restaurant_id=1, name="Vacío", unit="kg", current_stock=0, ideal_stock=1),
                "Ajeno": InventoryItem(restaurant_id=2, name="Ajeno", unit="kg", current_stock=9, ideal_stock=1, cost=1),
            }
            db.add_all(items.values())
            db.flush()
            db.add_all(
                [
                    DishIngredient(restaurant_id=1, dish_id=tiramisu.id, inventory_item_id=items["Mascarpone"].id, quantity=0.1, unit="kg"),
                    DishIngredient(restaurant_id=1, dish_id=tiramisu.id, inventory_item_id=items["Café"].id, quantity=0.02, unit="kg"),
                    DishIngredient(restaurant_id=1, dish_id=old_dish.id, inventory_item_id=items["Nata"].id, quantity=0.1, unit="l"),
                    DishIngredient(restaurant_id=1, dish_id=tiramisu.id, inventory_item_id=items["Fresas"].id, quantity=0.05, unit="kg"),
                ]
            )
            now = datetime.utcnow()
            # Nata: 30 days of 0.1 l/day -> 30 days of cover: slow mover.
            for day in range(30):
                db.add(InventoryMovement(restaurant_id=1, inventory_item_id=items["Nata"].id, movement_type="OUT", quantity=0.1, unit="l", reason="sale", created_at=now - timedelta(days=day, hours=1)))
            # Fresas: thrown away recently.
            db.add(InventoryMovement(restaurant_id=1, inventory_item_id=items["Fresas"].id, movement_type="WASTE", quantity=0.5, unit="kg", reason="Estropeado", loss_category="spoilage", created_at=now - timedelta(days=2)))
            db.commit()
            self.ids = {name: item.id for name, item in items.items()}

    def tearDown(self):
        app.dependency_overrides.clear()

    @contextmanager
    def client_as(self, user_id: int):
        restaurant_id = 1 if user_id < 6 else 2
        user = User(id=user_id, email=f"leftovers-{user_id}@hostai.test", hashed_password="x", role=ROLE_BY_USER[user_id], restaurant_id=restaurant_id, is_active=True, created_at=datetime.utcnow())
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = lambda: restaurant_id
        with TestClient(app) as client:
            yield client

    # --- Detection -------------------------------------------------------------

    def test_detects_overstock_slow_rotation_waste_and_unused(self):
        with self.client_as(2) as manager:
            response = manager.get("/api/inventory/leftovers")

        self.assertEqual(response.status_code, 200, response.text)
        items = {item["name"]: item for item in response.json()["items"]}
        self.assertEqual(set(items), {"Mascarpone", "Nata", "Fresas", "Azafrán"})
        codes = {name: {reason["code"] for reason in item["reasons"]} for name, item in items.items()}
        self.assertEqual(codes["Mascarpone"], {"overstock"})
        self.assertEqual(codes["Nata"], {"slow"})
        # Its only movement was waste, so it is also slow-moving: both are true.
        self.assertEqual(codes["Fresas"], {"waste", "slow"})
        self.assertEqual(codes["Azafrán"], {"unused"})
        # Waste is the most urgent reason and comes first.
        self.assertEqual(response.json()["items"][0]["name"], "Fresas")
        mascarpone_dish = items["Mascarpone"]["dishes"][0]
        self.assertEqual((mascarpone_dish["name"], mascarpone_dish["servings_possible"]), ("Tiramisú", 70))
        self.assertFalse(items["Nata"]["dishes"][0]["is_active"])

    # --- AI ideas --------------------------------------------------------------------

    def _ask(self, client: TestClient, names: list[str]):
        return client.post(
            "/api/inventory/leftovers/ideas",
            json={"restaurant_id": 1, "ingredient_ids": [self.ids[name] for name in names]},
        )

    def test_ideas_keep_only_known_ingredients_and_compute_cost_locally(self):
        canned = {
            "ideas": [
                {
                    "nombre": "Mousse de mascarpone",
                    "descripcion": "Ligera",
                    "por_que": "Gasta el sobrante",
                    "ingredientes": [
                        {"id": self.ids["Mascarpone"], "cantidad": 0.08},
                        {"id": self.ids["Café"], "cantidad": "0.01"},
                        {"id": 99999, "cantidad": 1},
                        {"id": self.ids["Ajeno"], "cantidad": 1},
                        {"id": self.ids["Nata"], "cantidad": -3},
                    ],
                    "coste": 0.01,
                },
                {"nombre": "Sin lo que sobra", "ingredientes": [{"id": self.ids["Café"], "cantidad": 0.01}]},
                {"nombre": "", "ingredientes": []},
            ]
        }
        with patch.object(openai_service, "json_completion", return_value=canned) as completion, self.client_as(1) as owner:
            response = self._ask(owner, ["Mascarpone"])

        self.assertEqual(response.status_code, 200, response.text)
        ideas = response.json()["ideas"]
        self.assertEqual([idea["name"] for idea in ideas], ["Mousse de mascarpone"])
        self.assertEqual([line["name"] for line in ideas[0]["ingredients"]], ["Mascarpone", "Café"])
        # 0.08 x 8 + 0.01 x 11 = 0.75, ignoring the model's own "coste".
        self.assertEqual(ideas[0]["estimated_cost"], 0.75)
        self.assertEqual(ideas[0]["suggested_price"], 2.75)
        prompt = json.loads(completion.call_args.kwargs["prompt"])
        self.assertNotIn("Ajeno", json.dumps(prompt, ensure_ascii=False))

    def test_ai_failure_returns_a_friendly_error(self):
        with patch.object(openai_service, "json_completion", return_value={"error": "AI service unavailable"}), self.client_as(1) as owner:
            response = self._ask(owner, ["Mascarpone"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ideas"], [])
        self.assertIn("no está disponible", response.json()["error"])

    def test_ideas_are_rate_limited_per_restaurant(self):
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=3600)
        with patch.object(inventory_router, "leftover_ideas_rate_limiter", limiter), patch.object(
            openai_service, "json_completion", return_value={"ideas": []}
        ) as completion, self.client_as(1) as owner:
            statuses = [self._ask(owner, ["Mascarpone"]).status_code for _ in range(3)]

        self.assertEqual(statuses, [200, 200, 429])
        self.assertEqual(completion.call_count, 2)

    # --- Access ----------------------------------------------------------------------

    def test_access_is_limited_to_owner_and_manager_of_the_restaurant(self):
        with patch.object(openai_service, "json_completion", return_value={"ideas": []}) as completion:
            for user_id in (3, 4):
                with self.subTest(role=ROLE_BY_USER[user_id]), self.client_as(user_id) as staff:
                    self.assertEqual(staff.get("/api/inventory/leftovers").status_code, 403)
                    self.assertEqual(self._ask(staff, ["Mascarpone"]).status_code, 403)
                    self.assertEqual(staff.get("/admin/leftovers").status_code, 403)
            with self.client_as(1) as owner:
                foreign_items = owner.post("/api/inventory/leftovers/ideas", json={"restaurant_id": 1, "ingredient_ids": [self.ids["Ajeno"]]})
                page = owner.get("/admin/leftovers")
            with self.client_as(6) as other_owner:
                foreign_restaurant = self._ask(other_owner, ["Mascarpone"])

        self.assertEqual(foreign_items.status_code, 404)
        self.assertEqual(foreign_restaurant.status_code, 403)
        self.assertEqual(page.status_code, 200)
        self.assertIn('href="/admin/leftovers"', page.text)
        completion.assert_not_called()


if __name__ == "__main__":
    unittest.main()

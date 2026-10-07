import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import selectinload, sessionmaker

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    Category,
    Dish,
    DishIngredient,
    InventoryItem,
    Restaurant,
    RestaurantMembership,
    User,
)
from app.services.costing_service import list_dish_costings
from app.services.customer_order_service import _dish_is_available
from app.services.historical_valuation_service import value_recipe_consumption
from app.services.planning_service import _impact_lines
from app.utils.demo_seed import seed_demo_database

ROLE_BY_USER = {1: "owner", 2: "manager", 3: "waiter", 4: "cook", 6: "owner"}


class RecipesCostingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/recipes.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        with cls.SessionTesting() as db:
            db.add_all(
                [
                    Restaurant(id=1, name="Centro", slug="recipes-centro", vat_percentage=10),
                    Restaurant(id=2, name="Playa", slug="recipes-playa"),
                ]
            )
            for user_id, role in ROLE_BY_USER.items():
                restaurant_id = 1 if user_id < 6 else 2
                db.add(User(id=user_id, email=f"recipes-{user_id}@hostai.test", hashed_password="x", role=role, restaurant_id=restaurant_id))
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
        with self.SessionTesting() as db:
            for model in (DishIngredient, InventoryItem, Dish, Category):
                db.execute(delete(model))
            db.get(Restaurant, 1).vat_percentage = 10
            db.commit()
            category = Category(restaurant_id=1, name="Pescados")
            db.add(category)
            db.flush()
            # 11.00 with 10 % VAT -> 10.00 without VAT: easy percentages.
            dish = Dish(restaurant_id=1, category_id=category.id, name="Lubina", price=11)
            fish = InventoryItem(restaurant_id=1, name="Lubina entera", unit="kg", current_stock=0.15, cost=10)
            lemon = InventoryItem(restaurant_id=1, name="Limón", unit="unit", current_stock=10, cost=0.3)
            foreign_item = InventoryItem(restaurant_id=2, name="Ajeno", unit="kg", current_stock=1, cost=1)
            db.add_all([dish, fish, lemon, foreign_item])
            db.flush()
            # 0.1 kg on the plate at 50 % yield -> 0.2 kg out of the store room -> 2.00 EUR.
            line = DishIngredient(restaurant_id=1, dish_id=dish.id, inventory_item_id=fish.id, quantity=0.1, unit="kg", yield_percentage=50)
            db.add(line)
            db.commit()
            self.dish_id, self.fish_id, self.lemon_id, self.line_id = dish.id, fish.id, lemon.id, line.id
            self.foreign_item_id = foreign_item.id

    def tearDown(self):
        app.dependency_overrides.clear()

    @contextmanager
    def client_as(self, user_id: int):
        restaurant_id = 1 if user_id < 6 else 2
        user = User(id=user_id, email=f"recipes-{user_id}@hostai.test", hashed_password="x", role=ROLE_BY_USER[user_id], restaurant_id=restaurant_id, is_active=True, created_at=datetime.utcnow())
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = lambda: restaurant_id
        with TestClient(app) as client:
            yield client

    def _costing(self, client: TestClient) -> dict:
        response = client.get(f"/api/restaurants/1/dishes/{self.dish_id}/costing")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    # --- Escandallo ---------------------------------------------------------

    def test_escandallo_costs_gross_quantity_and_measures_without_vat(self):
        with self.client_as(1) as owner:
            costing = self._costing(owner)

        line = costing["ingredients_breakdown"][0]
        self.assertAlmostEqual(line["gross_quantity"], 0.2)
        self.assertEqual(line["yield_percentage"], 50)
        self.assertEqual(line["line_cost"], 2.0)
        self.assertEqual(costing["total_cost"], 2.0)
        self.assertEqual(costing["price_without_vat"], 10.0)
        self.assertEqual(costing["food_cost_percentage"], 20.0)
        self.assertEqual(costing["net_margin"], 8.0)
        self.assertEqual(costing["net_margin_percentage"], 80.0)
        # Legacy fields keep their original meaning (price with VAT).
        self.assertEqual(costing["gross_margin"], 9.0)

    def test_changing_vat_recalculates_escandallo(self):
        with self.client_as(2) as manager:
            update = manager.patch("/api/restaurants/1", json={"vat_percentage": 21})
            too_high = manager.patch("/api/restaurants/1", json={"vat_percentage": 50})
            costing = self._costing(manager)

        self.assertEqual(update.status_code, 200, update.text)
        self.assertEqual(too_high.status_code, 422)
        self.assertEqual(costing["vat_percentage"], 21.0)
        self.assertEqual(costing["price_without_vat"], 9.09)

    def test_legacy_line_with_foreign_unit_is_flagged(self):
        with self.SessionTesting() as db:
            db.add(DishIngredient(restaurant_id=1, dish_id=self.dish_id, inventory_item_id=self.lemon_id, quantity=50, unit="g"))
            db.commit()
        with self.client_as(1) as owner:
            costing = self._costing(owner)

        lemon = next(line for line in costing["ingredients_breakdown"] if line["ingredient_name"] == "Limón")
        self.assertTrue(lemon["unit_mismatch"])

    # --- Yield drives stock as well as cost -------------------------------------

    def test_yield_drives_consumption_availability_and_planning(self):
        with self.SessionTesting() as db:
            line = db.scalar(
                select(DishIngredient).options(selectinload(DishIngredient.inventory_item)).where(DishIngredient.id == self.line_id)
            )
            quantity, unit_cost, total = value_recipe_consumption(line, 2)
            self.assertAlmostEqual(quantity, 0.4)
            self.assertEqual(total, 4.0)
            impact = _impact_lines(line.inventory_item, [line])[0]
            self.assertAlmostEqual(impact.required_quantity, 0.2)
            # 0.15 kg in stock is enough for 0.1 kg net, but not for the 0.2 kg gross.
            self.assertTrue(impact.is_blocked)
            dish = db.scalar(
                select(Dish)
                .options(selectinload(Dish.dish_ingredients).selectinload(DishIngredient.inventory_item))
                .where(Dish.id == self.dish_id)
            )
            self.assertFalse(_dish_is_available(dish))

    # --- Recipe lines -------------------------------------------------------------

    def test_recipe_lines_can_be_added_edited_and_removed(self):
        with self.client_as(2) as manager:
            created = manager.post(
                "/api/inventory/dish-ingredients",
                json={"restaurant_id": 1, "dish_id": self.dish_id, "inventory_item_id": self.lemon_id, "quantity": 0.5, "unit": "unit"},
            )
            self.assertEqual(created.status_code, 200, created.text)
            self.assertEqual(created.json()["yield_percentage"], 100)
            edited = manager.patch(f"/api/inventory/dish-ingredients/{self.line_id}", json={"quantity": 0.12, "yield_percentage": 60})
            invalid = manager.patch(f"/api/inventory/dish-ingredients/{self.line_id}", json={"yield_percentage": 0})
            over = manager.patch(f"/api/inventory/dish-ingredients/{self.line_id}", json={"yield_percentage": 101})
            removed = manager.delete(f"/api/inventory/dish-ingredients/{created.json()['id']}")
            costing = self._costing(manager)

        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual((edited.json()["quantity"], edited.json()["yield_percentage"]), (0.12, 60))
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(over.status_code, 422)
        self.assertEqual(removed.status_code, 204)
        self.assertEqual(len(costing["ingredients_breakdown"]), 1)
        self.assertAlmostEqual(costing["ingredients_breakdown"][0]["gross_quantity"], 0.2)

    def test_recipe_lines_are_protected_by_role_and_restaurant(self):
        with self.client_as(3) as waiter:
            waiter_edit = waiter.patch(f"/api/inventory/dish-ingredients/{self.line_id}", json={"quantity": 1})
            waiter_delete = waiter.delete(f"/api/inventory/dish-ingredients/{self.line_id}")
        with self.client_as(6) as other_owner:
            foreign_edit = other_owner.patch(f"/api/inventory/dish-ingredients/{self.line_id}", json={"quantity": 1})
            foreign_page = other_owner.get("/api/restaurants/1/recipes")
        with self.client_as(1) as owner:
            missing = owner.delete("/api/inventory/dish-ingredients/999999")

        self.assertEqual({waiter_edit.status_code, waiter_delete.status_code, foreign_edit.status_code}, {403})
        self.assertEqual(foreign_page.status_code, 403)
        self.assertEqual(missing.status_code, 404)
        with self.SessionTesting() as db:
            self.assertEqual(db.get(DishIngredient, self.line_id).quantity, 0.1)

    # --- Screen ---------------------------------------------------------------------

    def test_recipes_screen_and_api_for_owner_and_manager_only(self):
        for user_id in (1, 2):
            with self.subTest(role=ROLE_BY_USER[user_id]), self.client_as(user_id) as staff:
                api = staff.get("/api/restaurants/1/recipes")
                self.assertEqual(api.status_code, 200, api.text)
                self.assertEqual(staff.get("/admin/recipes").status_code, 200)
        for user_id in (3, 4):
            with self.subTest(role=ROLE_BY_USER[user_id]), self.client_as(user_id) as staff:
                self.assertEqual(staff.get("/api/restaurants/1/recipes").status_code, 403)
                self.assertEqual(staff.get("/admin/recipes").status_code, 403)

        payload = api.json()
        self.assertEqual(payload["vat_percentage"], 10.0)
        self.assertEqual({item["name"] for item in payload["ingredients"]}, {"Lubina entera", "Limón"})
        self.assertEqual(payload["dishes"][0]["food_cost_percentage"], 20.0)


class DemoSeedCostingTests(unittest.TestCase):
    def test_demo_escandallos_are_plausible(self):
        # Regression: Mozzarella was stored in grams with a per-kilo cost,
        # making Pizza Margarita cost 631 EUR.
        with tempfile.TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{temp_dir}/demo.db")
            Base.metadata.create_all(bind=engine)
            session = sessionmaker(bind=engine)
            with session() as db:
                seed_demo_database(db)
                restaurant_id = db.scalar(select(Restaurant.id).where(Restaurant.slug == "demo-restaurant"))
                costings = list_dish_costings(db, restaurant_id).dishes
            engine.dispose()

        with_recipe = [dish for dish in costings if dish.has_recipe]
        self.assertTrue(with_recipe)
        for dish in with_recipe:
            with self.subTest(dish=dish.dish_name):
                self.assertLess(dish.total_cost, dish.sale_price)


if __name__ == "__main__":
    unittest.main()

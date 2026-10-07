import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    Category,
    Dish,
    DishIngredient,
    InventoryItem,
    InventoryMovement,
    Restaurant,
    RestaurantMembership,
    User,
)
from app.schemas.inventory import InventoryMovementCreate
from app.services.inventory_service import create_inventory_movement_record

ROLE_BY_USER = {1: "owner", 2: "manager", 3: "waiter", 4: "cook", 5: "viewer", 6: "owner"}


class InventoryManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/inventory_management.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        with cls.SessionTesting() as db:
            db.add_all(
                [
                    Restaurant(id=1, name="Centro", slug="inventory-centro"),
                    Restaurant(id=2, name="Playa", slug="inventory-playa"),
                ]
            )
            for user_id, role in ROLE_BY_USER.items():
                restaurant_id = 1 if user_id < 6 else 2
                db.add(
                    User(
                        id=user_id,
                        email=f"inventory-{user_id}@hostai.test",
                        hashed_password="not-used",
                        role=role,
                        restaurant_id=restaurant_id,
                        is_active=True,
                    )
                )
                db.flush()
                db.add(
                    RestaurantMembership(
                        user_id=user_id,
                        restaurant_id=restaurant_id,
                        role=role,
                        is_active=True,
                        created_by_user_id=user_id,
                    )
                )
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
            for model in (InventoryMovement, DishIngredient, InventoryItem, Dish, Category):
                db.execute(delete(model))
            db.commit()
            category = Category(restaurant_id=1, name="Principales")
            db.add(category)
            db.flush()
            dish = Dish(restaurant_id=1, category_id=category.id, name="Pizza", price=10)
            tomato = InventoryItem(restaurant_id=1, name="Tomate", unit="kg", current_stock=6, cost=2.1)
            basil = InventoryItem(restaurant_id=1, name="Albahaca", unit="kg", current_stock=0, cost=9.5)
            foreign = InventoryItem(restaurant_id=2, name="Ajeno", unit="kg", current_stock=1)
            db.add_all([dish, tomato, basil, foreign])
            db.flush()
            db.add(DishIngredient(restaurant_id=1, dish_id=dish.id, inventory_item_id=tomato.id, quantity=0.1, unit="kg"))
            db.commit()
            self.dish_id, self.tomato_id, self.basil_id, self.foreign_id = dish.id, tomato.id, basil.id, foreign.id

    def tearDown(self):
        app.dependency_overrides.clear()

    @contextmanager
    def client_as(self, user_id: int):
        restaurant_id = 1 if user_id < 6 else 2
        user = User(
            id=user_id,
            email=f"inventory-{user_id}@hostai.test",
            hashed_password="not-used",
            role=ROLE_BY_USER[user_id],
            restaurant_id=restaurant_id,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = lambda: restaurant_id
        with TestClient(app) as client:
            yield client

    def _stock(self, item_id: int) -> float:
        with self.SessionTesting() as db:
            return db.get(InventoryItem, item_id).current_stock

    # --- Management view ----------------------------------------------------

    def test_management_view_reports_recipe_usage_and_unit_lock(self):
        with self.client_as(2) as manager:
            response = manager.get("/api/inventory/management")

        self.assertEqual(response.status_code, 200, response.text)
        items = {item["name"]: item for item in response.json()["items"]}
        self.assertEqual(set(items), {"Tomate", "Albahaca"})
        self.assertEqual(items["Tomate"]["used_in_dishes"], ["Pizza"])
        self.assertTrue(items["Tomate"]["unit_locked"])
        self.assertFalse(items["Albahaca"]["unit_locked"])

    def test_management_view_and_page_are_for_owner_and_manager(self):
        for user_id in (3, 4, 5):
            with self.subTest(role=ROLE_BY_USER[user_id]), self.client_as(user_id) as staff:
                self.assertEqual(staff.get("/api/inventory/management").status_code, 403)
                self.assertEqual(staff.get("/admin/inventory").status_code, 403)
        with self.client_as(1) as owner:
            page = owner.get("/admin/inventory")
            foreign = owner.get("/api/inventory/management?restaurant_id=2")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="inventoryAdminBootstrap"', page.text)
        self.assertIn('href="/admin/inventory"', page.text)
        self.assertEqual(foreign.status_code, 403)

    # --- Units --------------------------------------------------------------

    def test_manual_entries_must_use_the_item_unit(self):
        base = {"restaurant_id": 1, "inventory_item_id": self.tomato_id, "unit": "g"}
        with self.client_as(1) as owner:
            responses = {
                "intake": owner.post("/api/inventory/purchase-intakes", json={**base, "quantity": 500, "reason": "Compra"}),
                "adjustment": owner.post("/api/inventory/adjustments", json={**base, "stock_difference": -100, "reason": "Recuento"}),
                "waste": owner.post(
                    "/api/inventory/waste-losses",
                    json={**base, "quantity": 100, "reason": "Caducado", "loss_category": "expiration"},
                ),
                "movement": owner.post("/api/inventory/movements", json={**base, "movement_type": "OUT", "quantity": 100}),
            }

        for name, response in responses.items():
            with self.subTest(entry=name):
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()["error"]["code"], "inventory_unit_mismatch")
        self.assertEqual(self._stock(self.tomato_id), 6)

    def test_matching_unit_entries_still_work(self):
        base = {"restaurant_id": 1, "inventory_item_id": self.tomato_id, "unit": "kg"}
        with self.client_as(1) as owner:
            intake = owner.post("/api/inventory/purchase-intakes", json={**base, "quantity": 2, "unit_cost": 2.5, "reason": "Compra"})
            count = owner.post("/api/inventory/adjustments", json={**base, "stock_difference": -0.5, "reason": "Recuento"})

        self.assertEqual(intake.status_code, 200, intake.text)
        self.assertEqual(count.status_code, 200, count.text)
        self.assertAlmostEqual(self._stock(self.tomato_id), 7.5)

    def test_automatic_consumption_is_not_blocked_by_legacy_unit_mismatches(self):
        # Fulfillment consumes recipe lines; existing data must keep working.
        with self.SessionTesting() as db:
            create_inventory_movement_record(
                db,
                InventoryMovementCreate(
                    restaurant_id=1,
                    inventory_item_id=self.tomato_id,
                    movement_type="OUT",
                    quantity=1,
                    unit="g",
                ),
            )
            db.commit()
        self.assertEqual(self._stock(self.tomato_id), 5)

    def test_new_recipe_lines_must_use_the_item_unit(self):
        with self.client_as(1) as owner:
            response = owner.post(
                "/api/inventory/dish-ingredients",
                json={"restaurant_id": 1, "dish_id": self.dish_id, "inventory_item_id": self.basil_id, "quantity": 20, "unit": "g"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "recipe_unit_mismatch")

    def test_item_unit_must_be_supported_and_locks_once_used(self):
        with self.client_as(1) as owner:
            unsupported = owner.post("/api/inventory/items", json={"restaurant_id": 1, "name": "Cajas", "unit": "caja"})
            locked = owner.patch(f"/api/inventory/items/{self.tomato_id}", json={"unit": "g"})
            free = owner.patch(f"/api/inventory/items/{self.basil_id}", json={"unit": "G"})

        self.assertEqual(unsupported.status_code, 422)
        self.assertEqual(locked.status_code, 409)
        self.assertEqual(locked.json()["error"]["code"], "inventory_unit_locked")
        self.assertEqual(free.status_code, 200, free.text)
        self.assertEqual(free.json()["unit"], "g")

    def test_item_unit_locks_after_first_movement(self):
        with self.client_as(1) as owner:
            owner.post(
                "/api/inventory/purchase-intakes",
                json={"restaurant_id": 1, "inventory_item_id": self.basil_id, "quantity": 1, "unit": "kg", "reason": "Compra"},
            )
            response = owner.patch(f"/api/inventory/items/{self.basil_id}", json={"unit": "g"})

        self.assertEqual(response.status_code, 409)
        with self.SessionTesting() as db:
            self.assertEqual(db.scalar(select(InventoryItem.unit).where(InventoryItem.id == self.basil_id)), "kg")


if __name__ == "__main__":
    unittest.main()

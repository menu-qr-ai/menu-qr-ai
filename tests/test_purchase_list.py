import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import InventoryItem, InventoryMovement, Restaurant, RestaurantMembership, User
from app.services.planning_service import _round_up_to_step

ROLE_BY_USER = {1: "owner", 2: "manager", 3: "waiter", 4: "cook", 6: "owner"}


class PurchaseListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/purchase.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        with cls.SessionTesting() as db:
            db.add_all([Restaurant(id=1, name="Centro", slug="purchase-centro"), Restaurant(id=2, name="Playa", slug="purchase-playa")])
            for user_id, role in ROLE_BY_USER.items():
                restaurant_id = 1 if user_id < 6 else 2
                db.add(User(id=user_id, email=f"purchase-{user_id}@hostai.test", hashed_password="x", role=role, restaurant_id=restaurant_id))
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
            db.execute(delete(InventoryMovement))
            db.execute(delete(InventoryItem))
            db.commit()
            items = {
                # Below ideal, no consumption: order up to ideal (0.72 -> 0.8 kg).
                "Mozzarella": InventoryItem(restaurant_id=1, name="Mozzarella", unit="kg", current_stock=0.18, minimum_stock=0.25, ideal_stock=0.9, cost=4.2, supplier="Lácteos Norte"),
                # Consumes 1 kg/day: 7 days of cover beats the ideal of 5.
                "Harina": InventoryItem(restaurant_id=1, name="Harina", unit="kg", current_stock=2, minimum_stock=1, ideal_stock=5, cost=1.2, supplier="Molino Sur"),
                "Pimienta": InventoryItem(restaurant_id=1, name="Pimienta", unit="g", current_stock=35, ideal_stock=200, supplier=None),
                "Huevos": InventoryItem(restaurant_id=1, name="Huevos", unit="unit", current_stock=10, ideal_stock=36.5, cost=0.25, supplier="Granja"),
                "Sal": InventoryItem(restaurant_id=1, name="Sal", unit="kg", current_stock=10, ideal_stock=5, cost=0.5, supplier="Molino Sur"),
                "Retirado": InventoryItem(restaurant_id=1, name="Retirado", unit="kg", current_stock=0, ideal_stock=10, is_active=False, supplier="Molino Sur"),
                "Ajeno": InventoryItem(restaurant_id=2, name="Ajeno", unit="kg", current_stock=0, ideal_stock=10, supplier="Molino Sur"),
            }
            db.add_all(items.values())
            db.flush()
            now = datetime.utcnow()
            for day in range(30):
                db.add(
                    InventoryMovement(
                        restaurant_id=1,
                        inventory_item_id=items["Harina"].id,
                        movement_type="OUT",
                        quantity=1,
                        unit="kg",
                        reason="sale",
                        created_at=now - timedelta(days=day, hours=1),
                    )
                )
            db.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    @contextmanager
    def client_as(self, user_id: int):
        restaurant_id = 1 if user_id < 6 else 2
        user = User(id=user_id, email=f"purchase-{user_id}@hostai.test", hashed_password="x", role=ROLE_BY_USER[user_id], restaurant_id=restaurant_id, is_active=True, created_at=datetime.utcnow())
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = lambda: restaurant_id
        with TestClient(app) as client:
            yield client

    def _lines(self, payload: dict) -> dict:
        return {line["name"]: {**line, "supplier": group["supplier"]} for group in payload["groups"] for line in group["lines"]}

    def test_suggestions_target_ideal_or_real_consumption(self):
        with self.client_as(2) as manager:
            response = manager.get("/api/inventory/purchase-list")

        self.assertEqual(response.status_code, 200, response.text)
        lines = self._lines(response.json())
        self.assertEqual(set(lines), {"Mozzarella", "Harina", "Pimienta", "Huevos"})
        self.assertEqual(lines["Mozzarella"]["suggested_quantity"], 0.8)
        self.assertEqual(lines["Mozzarella"]["basis"], "ideal")
        self.assertEqual(lines["Mozzarella"]["estimated_cost"], 3.36)
        # 1 kg/day x 7 days = 7 kg target, 2 in stock -> 5 kg.
        self.assertEqual(lines["Harina"]["basis"], "consumption")
        self.assertEqual(lines["Harina"]["suggested_quantity"], 5)
        self.assertEqual(lines["Pimienta"]["suggested_quantity"], 170)
        self.assertIsNone(lines["Pimienta"]["estimated_cost"])
        self.assertEqual(lines["Huevos"]["suggested_quantity"], 27)

    def test_longer_coverage_orders_more(self):
        with self.client_as(1) as owner:
            response = owner.get("/api/inventory/purchase-list?coverage_days=14")

        lines = self._lines(response.json())
        self.assertEqual(response.json()["coverage_days"], 14)
        self.assertEqual(lines["Harina"]["suggested_quantity"], 12)
        self.assertEqual(lines["Mozzarella"]["suggested_quantity"], 0.8)

    def test_grouped_by_supplier_with_totals_and_no_supplier_last(self):
        with self.client_as(1) as owner:
            groups = owner.get("/api/inventory/purchase-list").json()["groups"]

        self.assertEqual(groups[-1]["supplier"], "Sin proveedor")
        self.assertTrue(groups[-1]["has_missing_costs"])
        molino = next(group for group in groups if group["supplier"] == "Molino Sur")
        self.assertEqual([line["name"] for line in molino["lines"]], ["Harina"])
        self.assertEqual(molino["estimated_total"], 6.0)

    def test_rounding_to_orderable_steps(self):
        self.assertEqual(_round_up_to_step(0.72, "kg"), 0.8)
        self.assertEqual(_round_up_to_step(1.2000000001, "kg"), 1.2)
        self.assertEqual(_round_up_to_step(721, "g"), 730)
        self.assertEqual(_round_up_to_step(26.5, "unit"), 27)
        self.assertEqual(_round_up_to_step(0.05, "l"), 0.1)

    def test_access_and_validation(self):
        for user_id in (3, 4):
            with self.subTest(role=ROLE_BY_USER[user_id]), self.client_as(user_id) as staff:
                self.assertEqual(staff.get("/api/inventory/purchase-list").status_code, 403)
                self.assertEqual(staff.get("/admin/purchasing").status_code, 403)
        with self.client_as(1) as owner:
            page = owner.get("/admin/purchasing")
            foreign = owner.get("/api/inventory/purchase-list?restaurant_id=2")
            too_short = owner.get("/api/inventory/purchase-list?coverage_days=0")
            too_long = owner.get("/api/inventory/purchase-list?coverage_days=61")

        self.assertEqual(page.status_code, 200)
        self.assertIn('id="purchasingAdminBootstrap"', page.text)
        self.assertIn('href="/admin/purchasing"', page.text)
        self.assertEqual(foreign.status_code, 403)
        self.assertEqual((too_short.status_code, too_long.status_code), (422, 422))


if __name__ == "__main__":
    unittest.main()

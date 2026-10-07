import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import AppError
from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    Category,
    Dish,
    Order,
    OrderLine,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    User,
    Zone,
)
from app.services import customer_order_service
from app.services.menu_service import get_menu_data

ROLE_BY_USER = {1: "owner", 2: "manager", 3: "waiter", 4: "cook", 5: "viewer", 6: "owner"}


class MenuManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/menu_management.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)
        with cls.SessionTesting() as db:
            db.add_all(
                [
                    Restaurant(id=1, name="Centro", slug="menu-centro"),
                    Restaurant(id=2, name="Playa", slug="menu-playa"),
                ]
            )
            for user_id, role in ROLE_BY_USER.items():
                restaurant_id = 1 if user_id < 6 else 2
                db.add(
                    User(
                        id=user_id,
                        email=f"menu-{user_id}@hostai.test",
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

        def override_get_db():
            db = cls.SessionTesting()
            try:
                yield db
            finally:
                db.close()

        cls.override_get_db = staticmethod(override_get_db)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls.temp_dir.cleanup()

    def setUp(self):
        app.dependency_overrides[get_db] = self.override_get_db
        with self.SessionTesting() as db:
            for model in (OrderLine, Order, ServiceSession, RestaurantTable, Zone, Dish, Category):
                db.execute(delete(model))
            db.commit()
            for restaurant_id in (1, 2):
                category = Category(name=f"Principales {restaurant_id}", restaurant_id=restaurant_id)
                db.add(category)
                db.flush()
                db.add(
                    Dish(
                        name=f"Lubina {restaurant_id}",
                        price=18.5,
                        category_id=category.id,
                        restaurant_id=restaurant_id,
                    )
                )
            db.commit()

    def tearDown(self):
        app.dependency_overrides.clear()

    @contextmanager
    def client_as(self, user_id: int):
        restaurant_id = 1 if user_id < 6 else 2
        user = User(
            id=user_id,
            email=f"menu-{user_id}@hostai.test",
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

    def _ids(self, restaurant_id: int = 1) -> tuple[int, int]:
        with self.SessionTesting() as db:
            dish = db.scalar(select(Dish).where(Dish.restaurant_id == restaurant_id))
            return dish.category_id, dish.id

    # --- Categories -------------------------------------------------------

    def test_category_lifecycle(self):
        with self.client_as(2) as manager:
            created = manager.post("/api/restaurants/1/categories", json={"name": "  Postres   caseros ", "display_order": 5})
            self.assertEqual(created.status_code, 201, created.text)
            category_id = created.json()["id"]
            self.assertEqual(created.json()["name"], "Postres caseros")

            renamed = manager.patch(f"/api/restaurants/1/categories/{category_id}", json={"name": "Postres", "display_order": 1})
            self.assertEqual(renamed.status_code, 200, renamed.text)
            self.assertEqual((renamed.json()["name"], renamed.json()["display_order"]), ("Postres", 1))

            listing = manager.get("/api/restaurants/1/menu-management").json()
            self.assertEqual([c["name"] for c in listing["categories"]], ["Principales 1", "Postres"])
            self.assertEqual(listing["categories"][1]["dish_count"], 0)

            deleted = manager.delete(f"/api/restaurants/1/categories/{category_id}")
            self.assertEqual(deleted.status_code, 204)

    def test_category_name_must_be_unique_ignoring_case_and_not_blank(self):
        with self.client_as(1) as owner:
            duplicate = owner.post("/api/restaurants/1/categories", json={"name": "principales 1"})
            blank = owner.post("/api/restaurants/1/categories", json={"name": "   "})

        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "category_name_conflict")
        self.assertEqual(blank.status_code, 422)

    def test_category_with_dishes_cannot_be_deleted(self):
        category_id, _ = self._ids()
        with self.client_as(1) as owner:
            response = owner.delete(f"/api/restaurants/1/categories/{category_id}")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "category_not_empty")

    # --- Dishes -----------------------------------------------------------

    def test_dish_partial_update_keeps_other_fields(self):
        _, dish_id = self._ids()
        with self.client_as(2) as manager:
            response = manager.patch(
                f"/api/restaurants/1/dishes/{dish_id}",
                json={"description": "Con patata panadera", "price": "19.90"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["name"], "Lubina 1")
        self.assertEqual(payload["price"], "19.90")
        self.assertEqual(payload["description"], "Con patata panadera")
        self.assertTrue(payload["is_active"])

    def test_dish_update_rejects_foreign_category_and_bad_price(self):
        foreign_category_id, _ = self._ids(restaurant_id=2)
        _, dish_id = self._ids()
        with self.client_as(1) as owner:
            foreign = owner.patch(f"/api/restaurants/1/dishes/{dish_id}", json={"category_id": foreign_category_id})
            bad_price = owner.patch(f"/api/restaurants/1/dishes/{dish_id}", json={"price": "2.805"})

        self.assertEqual(foreign.status_code, 404)
        self.assertEqual(foreign.json()["error"]["code"], "category_not_found")
        self.assertEqual(bad_price.status_code, 422)

    def test_hidden_dish_leaves_menus_and_ordering_but_stays_in_management(self):
        _, dish_id = self._ids()
        with self.client_as(1) as owner:
            hidden = owner.patch(f"/api/restaurants/1/dishes/{dish_id}", json={"is_active": False})
            self.assertEqual(hidden.status_code, 200, hidden.text)
            management = owner.get("/api/restaurants/1/menu-management").json()
            public_page = owner.get("/r/menu-centro/menu")

        self.assertEqual([d["is_active"] for d in management["dishes"]], [False])
        self.assertNotIn("Lubina 1", public_page.text)
        with self.SessionTesting() as db:
            self.assertEqual(get_menu_data(db, 1)["dishes"], [])
            self.assertEqual(customer_order_service._load_customer_dishes(db, 1), [])
            with self.assertRaises(AppError) as customer_error:
                customer_order_service._require_customer_dish(db, 1, dish_id)
        self.assertEqual(customer_error.exception.code, "customer_dish_not_found")

    def test_waiter_cannot_add_hidden_dish_to_order(self):
        _, dish_id = self._ids()
        with self.SessionTesting() as db:
            zone = Zone(restaurant_id=1, name="Sala")
            db.add(zone)
            db.flush()
            table = RestaurantTable(restaurant_id=1, zone_id=zone.id, code="M1", capacity=4)
            db.add(table)
            db.flush()
            service_session = ServiceSession(
                restaurant_id=1,
                table_id=table.id,
                status="open",
                opened_at=datetime.utcnow(),
                guest_count=2,
                opened_by_user_id=1,
            )
            db.add(service_session)
            db.get(Dish, dish_id).is_active = False
            db.commit()
            session_id = service_session.id

        with self.client_as(3) as waiter:
            order = waiter.post(f"/api/orders/1/sessions/{session_id}", json={"note": None})
            self.assertEqual(order.status_code, 201, order.text)
            response = waiter.post(
                f"/api/orders/1/{order.json()['id']}/lines",
                json={"dish_id": dish_id, "quantity": 1},
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "dish_inactive")

    # --- Access control ---------------------------------------------------

    def test_only_owner_and_manager_can_change_the_menu(self):
        category_id, dish_id = self._ids()
        for user_id in (3, 4, 5):
            with self.subTest(role=ROLE_BY_USER[user_id]), self.client_as(user_id) as staff:
                create = staff.post("/api/restaurants/1/categories", json={"name": "Nueva"})
                rename = staff.patch(f"/api/restaurants/1/categories/{category_id}", json={"name": "X"})
                hide = staff.patch(f"/api/restaurants/1/dishes/{dish_id}", json={"is_active": False})
                page = staff.get("/admin/menu", follow_redirects=False)
                self.assertEqual({create.status_code, rename.status_code, hide.status_code}, {403})
                self.assertEqual(page.status_code, 403)

    def test_management_is_isolated_per_restaurant(self):
        foreign_category_id, foreign_dish_id = self._ids(restaurant_id=2)
        with self.client_as(1) as owner:
            listing = owner.get("/api/restaurants/2/menu-management")
            hide_via_own_restaurant = owner.patch(f"/api/restaurants/1/dishes/{foreign_dish_id}", json={"is_active": False})
            delete_via_own_restaurant = owner.delete(f"/api/restaurants/1/categories/{foreign_category_id}")

        self.assertEqual(listing.status_code, 403)
        self.assertEqual(hide_via_own_restaurant.status_code, 404)
        self.assertEqual(delete_via_own_restaurant.status_code, 404)
        with self.SessionTesting() as db:
            self.assertTrue(db.get(Dish, foreign_dish_id).is_active)

    def test_management_page_renders_for_owner(self):
        with self.client_as(1) as owner:
            response = owner.get("/admin/menu")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="menuAdminBootstrap"', response.text)
        self.assertIn("Lubina 1", response.text)
        self.assertIn('href="/admin/menu"', response.text)


if __name__ == "__main__":
    unittest.main()

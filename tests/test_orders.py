import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    AnalyticsEvent,
    Category,
    Dish,
    InventoryMovement,
    Order,
    OrderLine,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    User,
    Zone,
)


class OrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/orders.db",
            connect_args={"check_same_thread": False},
        )
        cls.SessionTesting = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=cls.engine,
        )
        Base.metadata.create_all(bind=cls.engine)
        cls._seed_access()

        def override_get_db():
            db = cls.SessionTesting()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()
        cls.temp_dir.cleanup()

    @classmethod
    def _seed_access(cls):
        with cls.SessionTesting() as db:
            restaurants = [
                Restaurant(id=1, name="Centro", slug="orders-centro"),
                Restaurant(id=2, name="Playa", slug="orders-playa"),
            ]
            roles = ("owner", "manager", "waiter", "cook", "viewer", "owner")
            users = [
                User(
                    id=index,
                    email=f"orders-{index}@hostai.test",
                    hashed_password="not-used",
                    full_name=f"Orders {role.title()} {index}",
                    role=role,
                    restaurant_id=1 if index < 6 else 2,
                    is_active=True,
                    created_at=datetime.utcnow(),
                )
                for index, role in enumerate(roles, start=1)
            ]
            memberships = [
                RestaurantMembership(
                    user_id=index,
                    restaurant_id=1 if index < 6 else 2,
                    role=role,
                    is_active=True,
                    created_by_user_id=1 if index < 6 else 6,
                )
                for index, role in enumerate(roles, start=1)
            ]
            memberships.append(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=2,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            db.add_all([*restaurants, *users, *memberships])
            db.commit()

    def setUp(self):
        with self.SessionTesting() as db:
            db.execute(delete(OrderLine))
            db.execute(delete(Order))
            db.execute(delete(ServiceSession))
            db.execute(delete(RestaurantTable))
            db.execute(delete(Zone))
            db.execute(delete(Dish))
            db.execute(delete(Category))
            db.commit()
            for restaurant_id in (1, 2):
                category = Category(
                    name=f"Menu {restaurant_id}",
                    restaurant_id=restaurant_id,
                )
                db.add(category)
                db.flush()
                db.add(
                    Dish(
                        name=f"Dish {restaurant_id}",
                        price=10.5 + restaurant_id,
                        category_id=category.id,
                        restaurant_id=restaurant_id,
                    )
                )
            db.commit()

    @contextmanager
    def client_as(self, user_id: int, *, active_restaurant_id: int = 1):
        role_by_user = {
            1: "owner",
            2: "manager",
            3: "waiter",
            4: "cook",
            5: "viewer",
            6: "owner",
        }
        user = User(
            id=user_id,
            email=f"orders-{user_id}@hostai.test",
            hashed_password="not-used",
            full_name=f"Orders {role_by_user[user_id].title()}",
            role=role_by_user[user_id],
            restaurant_id=active_restaurant_id,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_active_restaurant_id] = (
            lambda: active_restaurant_id
        )
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_active_restaurant_id, None)

    def _open_session(self, client: TestClient, restaurant_id: int = 1) -> dict:
        del client
        with self.SessionTesting() as db:
            zone = Zone(
                restaurant_id=restaurant_id,
                name=f"Zone {restaurant_id}",
            )
            db.add(zone)
            db.flush()
            table = RestaurantTable(
                restaurant_id=restaurant_id,
                zone_id=zone.id,
                code=f"M{restaurant_id}",
                capacity=4,
            )
            db.add(table)
            db.flush()
            service_session = ServiceSession(
                restaurant_id=restaurant_id,
                table_id=table.id,
                status="open",
                opened_at=datetime.utcnow(),
                guest_count=2,
                opened_by_user_id=1 if restaurant_id == 1 else 6,
            )
            db.add(service_session)
            db.commit()
            return {"id": service_session.id, "restaurant_id": restaurant_id}

    def _dish_id(self, restaurant_id: int = 1) -> int:
        with self.SessionTesting() as db:
            return db.scalar(
                select(Dish.id).where(Dish.restaurant_id == restaurant_id)
            )

    def _create_order(
        self,
        client: TestClient,
        session_id: int,
        *,
        restaurant_id: int = 1,
        idempotency_key: str | None = None,
    ) -> dict:
        response = client.post(
            f"/api/orders/{restaurant_id}/sessions/{session_id}",
            json={"note": "First round", "idempotency_key": idempotency_key},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _add_line(
        self,
        client: TestClient,
        order_id: int,
        *,
        restaurant_id: int = 1,
        quantity: int = 2,
        idempotency_key: str | None = None,
    ) -> dict:
        response = client.post(
            f"/api/orders/{restaurant_id}/{order_id}/lines",
            json={
                "dish_id": self._dish_id(restaurant_id),
                "quantity": quantity,
                "note": "No salt",
                "idempotency_key": idempotency_key,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_order_line_crud_and_price_snapshot(self):
        with self.client_as(3) as waiter:
            session = self._open_session(waiter)
            order = self._create_order(waiter, session["id"])
            order = self._add_line(waiter, order["id"])
            line = order["lines"][0]
            original_price = line["unit_price"]

            with self.SessionTesting() as db:
                dish = db.get(Dish, line["dish_id"])
                dish.price = 99
                db.commit()

            updated = waiter.patch(
                f"/api/orders/1/{order['id']}/lines/{line['id']}",
                json={"quantity": 3, "note": "Allergy note"},
            )
            removed = waiter.delete(
                f"/api/orders/1/{order['id']}/lines/{line['id']}"
            )

        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["lines"][0]["quantity"], 3)
        self.assertEqual(updated.json()["lines"][0]["unit_price"], original_price)
        expected_total = format(Decimal(original_price) * 3, ".2f")
        self.assertEqual(updated.json()["lines"][0]["subtotal"], expected_total)
        self.assertEqual(updated.json()["total_amount"], expected_total)
        self.assertEqual(updated.json()["total_units"], 3)
        self.assertEqual(removed.status_code, 204)

    def test_decimal_snapshot_totals_and_later_price_change(self):
        with self.SessionTesting() as db:
            dish = db.scalar(select(Dish).where(Dish.restaurant_id == 1))
            dish.price = Decimal("0.10")
            db.commit()

        with self.client_as(3) as waiter:
            session = self._open_session(waiter)
            order = self._create_order(waiter, session["id"])
            first = self._add_line(waiter, order["id"], quantity=1)
            combined = self._add_line(waiter, order["id"], quantity=2)

            with self.SessionTesting() as db:
                dish = db.get(Dish, first["lines"][0]["dish_id"])
                dish.price = Decimal("99.99")
                db.commit()

            historical = waiter.get(f"/api/orders/1/{order['id']}")

        self.assertEqual(first["lines"][0]["unit_price"], "0.10")
        self.assertEqual(first["lines"][0]["subtotal"], "0.10")
        self.assertEqual(combined["total_amount"], "0.30")
        self.assertEqual(historical.status_code, 200)
        self.assertEqual(
            [line["unit_price"] for line in historical.json()["lines"]],
            ["0.10", "0.10"],
        )
        self.assertEqual(historical.json()["total_amount"], "0.30")

    def test_owner_and_manager_can_create_and_update_decimal_prices(self):
        with self.SessionTesting() as db:
            category_id = db.scalar(
                select(Category.id).where(Category.restaurant_id == 1)
            )

        payload = {
            "name": "Decimal dish",
            "description": "",
            "price": "10.95",
            "ingredients": "",
            "allergens": "",
            "image": "",
            "category_id": category_id,
        }
        with self.client_as(1) as owner:
            created = owner.post("/api/restaurants/1/dishes", json=payload)
        with self.client_as(2) as manager:
            updated = manager.patch(
                f"/api/restaurants/1/dishes/{created.json()['id']}/price",
                json={"price": "11.05"},
            )

        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["price"], "10.95")
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["price"], "11.05")

    def test_price_validation_permissions_and_tenant_isolation(self):
        dish_one = self._dish_id(1)
        dish_two = self._dish_id(2)

        with self.client_as(3) as waiter:
            forbidden = waiter.patch(
                f"/api/restaurants/1/dishes/{dish_one}/price",
                json={"price": "12.00"},
            )
        with self.client_as(1) as owner:
            negative = owner.patch(
                f"/api/restaurants/1/dishes/{dish_one}/price",
                json={"price": "-0.01"},
            )
            excess_scale = owner.patch(
                f"/api/restaurants/1/dishes/{dish_one}/price",
                json={"price": "1.234"},
            )
            non_finite = owner.patch(
                f"/api/restaurants/1/dishes/{dish_one}/price",
                json={"price": "NaN"},
            )
            wrong_tenant = owner.patch(
                f"/api/restaurants/1/dishes/{dish_two}/price",
                json={"price": "12.00"},
            )
            nullable = owner.patch(
                f"/api/restaurants/1/dishes/{dish_one}/price",
                json={"price": None},
            )

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(negative.status_code, 422)
        self.assertEqual(excess_scale.status_code, 422)
        self.assertEqual(non_finite.status_code, 422)
        self.assertEqual(wrong_tenant.status_code, 404)
        self.assertEqual(nullable.status_code, 200)
        self.assertIsNone(nullable.json()["price"])

    def test_order_line_quantity_must_be_positive(self):
        with self.client_as(3) as waiter:
            session = self._open_session(waiter)
            order = self._create_order(waiter, session["id"])
            response = waiter.post(
                f"/api/orders/1/{order['id']}/lines",
                json={"dish_id": self._dish_id(), "quantity": 0},
            )

        self.assertEqual(response.status_code, 422)

    def test_one_session_supports_multiple_orders(self):
        with self.client_as(3) as waiter:
            session = self._open_session(waiter)
            first = self._create_order(waiter, session["id"])
            second = self._create_order(waiter, session["id"])
            response = waiter.get(f"/api/orders/1/sessions/{session['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()}, {first["id"], second["id"]})

    def test_submit_is_idempotent_and_freezes_lines(self):
        with self.client_as(3) as waiter:
            session = self._open_session(waiter)
            order = self._add_line(
                waiter,
                self._create_order(waiter, session["id"])["id"],
            )
            first = waiter.post(f"/api/orders/1/{order['id']}/submit")
            second = waiter.post(f"/api/orders/1/{order['id']}/submit")
            edit = waiter.patch(
                f"/api/orders/1/{order['id']}/lines/{order['lines'][0]['id']}",
                json={"quantity": 4},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["submitted_at"], second.json()["submitted_at"])
        self.assertEqual(edit.status_code, 409)
        self.assertEqual(edit.json()["error"]["code"], "order_not_editable")

    def test_invalid_transitions_and_empty_submit(self):
        with self.client_as(3) as waiter:
            session = self._open_session(waiter)
            empty = self._create_order(waiter, session["id"])
            empty_submit = waiter.post(f"/api/orders/1/{empty['id']}/submit")
            complete_draft = waiter.post(f"/api/orders/1/{empty['id']}/complete")
            cancelled = waiter.post(f"/api/orders/1/{empty['id']}/cancel")
            complete_cancelled = waiter.post(
                f"/api/orders/1/{empty['id']}/complete"
            )

        self.assertEqual(empty_submit.status_code, 409)
        self.assertEqual(empty_submit.json()["error"]["code"], "order_empty")
        self.assertEqual(complete_draft.status_code, 409)
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        self.assertEqual(complete_cancelled.status_code, 409)

    def test_session_cannot_close_with_active_order(self):
        with self.client_as(3) as waiter:
            session = self._open_session(waiter)
            order = self._create_order(waiter, session["id"])
            blocked = waiter.post(f"/api/dining/1/sessions/{session['id']}/close")
            waiter.post(f"/api/orders/1/{order['id']}/cancel")
            closed = waiter.post(f"/api/dining/1/sessions/{session['id']}/close")
            late_order = waiter.post(
                f"/api/orders/1/sessions/{session['id']}",
                json={},
            )

        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(
            blocked.json()["error"]["code"],
            "service_session_has_active_orders",
        )
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(late_order.status_code, 409)

    def test_idempotency_keys_prevent_double_creation(self):
        with self.client_as(3) as waiter:
            session = self._open_session(waiter)
            first = self._create_order(
                waiter,
                session["id"],
                idempotency_key="order-click",
            )
            second = self._create_order(
                waiter,
                session["id"],
                idempotency_key="order-click",
            )
            first_line = self._add_line(
                waiter,
                first["id"],
                idempotency_key="line-click",
            )
            second_line = self._add_line(
                waiter,
                first["id"],
                idempotency_key="line-click",
            )

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(first_line["lines"]), 1)
        self.assertEqual(len(second_line["lines"]), 1)

    def test_order_and_line_ids_are_tenant_isolated(self):
        with self.client_as(1) as owner:
            session_one = self._open_session(owner, 1)
            order_one = self._create_order(owner, session_one["id"], restaurant_id=1)
            session_two = self._open_session(owner, 2)
            order_two = self._create_order(owner, session_two["id"], restaurant_id=2)
            wrong_order = owner.get(f"/api/orders/1/{order_two['id']}")
            wrong_session = owner.get(
                f"/api/orders/1/sessions/{session_two['id']}"
            )
            wrong_dish = owner.post(
                f"/api/orders/1/{order_one['id']}/lines",
                json={"dish_id": self._dish_id(2), "quantity": 1},
            )

        self.assertEqual(wrong_order.status_code, 404)
        self.assertEqual(wrong_session.status_code, 404)
        self.assertEqual(wrong_dish.status_code, 404)

    def test_roles_and_unauthorized_restaurant(self):
        with self.client_as(1) as owner:
            session = self._open_session(owner)
            order = self._create_order(owner, session["id"])

        cases = (
            (2, "get", f"/api/orders/1/{order['id']}", 200),
            (3, "post", f"/api/orders/1/{order['id']}/cancel", 200),
            (4, "get", f"/api/orders/1/{order['id']}", 403),
            (5, "get", f"/api/orders/1/{order['id']}", 200),
            (5, "post", f"/api/orders/1/{order['id']}/cancel", 403),
            (2, "get", "/api/orders/2/sessions/9999", 403),
        )
        for user_id, method, path, expected in cases:
            with self.subTest(user_id=user_id, path=path), self.client_as(user_id) as client:
                response = getattr(client, method)(path)
                self.assertEqual(response.status_code, expected, response.text)

    def test_submit_does_not_create_sales_analytics_or_inventory_movements(self):
        with self.SessionTesting() as db:
            movements_before = db.scalar(select(func.count()).select_from(InventoryMovement))
            events_before = db.scalar(select(func.count()).select_from(AnalyticsEvent))

        with self.client_as(3) as waiter:
            session = self._open_session(waiter)
            order = self._add_line(
                waiter,
                self._create_order(waiter, session["id"])["id"],
            )
            submitted = waiter.post(f"/api/orders/1/{order['id']}/submit")

        with self.SessionTesting() as db:
            movements_after = db.scalar(select(func.count()).select_from(InventoryMovement))
            events_after = db.scalar(select(func.count()).select_from(AnalyticsEvent))

        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(movements_before, movements_after)
        self.assertEqual(events_before, events_after)

    def test_order_tables_compile_for_postgresql(self):
        for table_name in ("orders", "order_lines"):
            with self.subTest(table=table_name):
                sql = str(
                    CreateTable(Base.metadata.tables[table_name]).compile(
                        dialect=postgresql.dialect(),
                    )
                )
                self.assertIn(f"CREATE TABLE {table_name}", sql)

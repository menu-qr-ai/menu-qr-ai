import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    AnalyticsEvent,
    Category,
    CustomerSession,
    Dish,
    DishIngredient,
    InventoryItem,
    InventoryMovement,
    KitchenTicket,
    KitchenTicketLine,
    Order,
    OrderLine,
    QRCode,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    User,
    Zone,
)


class CustomerOrderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/customer-ordering.db",
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
                Restaurant(
                    id=1,
                    name="Customer Centro",
                    slug="customer-centro",
                    currency="EUR",
                ),
                Restaurant(
                    id=2,
                    name="Customer Playa",
                    slug="customer-playa",
                    currency="EUR",
                ),
            ]
            roles = (
                "owner",
                "manager",
                "waiter",
                "cook",
                "viewer",
                "owner",
            )
            users = [
                User(
                    id=index,
                    email=f"customer-{index}@hostai.test",
                    hashed_password="not-used",
                    full_name=f"Customer {role.title()}",
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
            db.add_all([*restaurants, *users, *memberships])
            db.commit()

    def setUp(self):
        with self.SessionTesting() as db:
            for model in (
                KitchenTicketLine,
                KitchenTicket,
                OrderLine,
                Order,
                CustomerSession,
                QRCode,
                ServiceSession,
                RestaurantTable,
                Zone,
                DishIngredient,
                InventoryMovement,
                InventoryItem,
                Dish,
                Category,
                AnalyticsEvent,
            ):
                db.execute(delete(model))
            db.commit()

            for restaurant_id, opener_id in ((1, 1), (2, 6)):
                category = Category(
                    restaurant_id=restaurant_id,
                    name=f"Menu {restaurant_id}",
                )
                zone = Zone(
                    restaurant_id=restaurant_id,
                    name=f"Zone {restaurant_id}",
                )
                ingredient = InventoryItem(
                    restaurant_id=restaurant_id,
                    name=f"Ingredient {restaurant_id}",
                    unit="unit",
                    current_stock=20,
                    minimum_stock=0,
                    ideal_stock=20,
                    cost=2,
                    is_active=True,
                )
                db.add_all([category, zone, ingredient])
                db.flush()
                available_dish = Dish(
                    restaurant_id=restaurant_id,
                    category_id=category.id,
                    name=f"Available dish {restaurant_id}",
                    description="Fresh",
                    price="10.50",
                    ingredients="Ingredient",
                    allergens="Gluten",
                )
                unavailable_dish = Dish(
                    restaurant_id=restaurant_id,
                    category_id=category.id,
                    name=f"Unavailable dish {restaurant_id}",
                    price="8.00",
                )
                table = RestaurantTable(
                    restaurant_id=restaurant_id,
                    zone_id=zone.id,
                    code=f"C-{restaurant_id}",
                    capacity=4,
                    is_active=True,
                )
                db.add_all(
                    [available_dish, unavailable_dish, table]
                )
                db.flush()
                db.add(
                    DishIngredient(
                        restaurant_id=restaurant_id,
                        dish_id=available_dish.id,
                        inventory_item_id=ingredient.id,
                        quantity=1,
                        unit="unit",
                    )
                )
                db.add(
                    ServiceSession(
                        restaurant_id=restaurant_id,
                        table_id=table.id,
                        status="open",
                        opened_at=datetime.utcnow(),
                        guest_count=2,
                        opened_by_user_id=opener_id,
                    )
                )
            db.commit()

    @contextmanager
    def client_as(
        self,
        user_id: int,
        *,
        active_restaurant_id: int = 1,
    ):
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
            email=f"customer-{user_id}@hostai.test",
            hashed_password="not-used",
            full_name=f"Customer {role_by_user[user_id].title()}",
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
            app.dependency_overrides.pop(
                get_current_user,
                None,
            )
            app.dependency_overrides.pop(
                get_active_restaurant_id,
                None,
            )

    def _table_id(self, restaurant_id: int = 1) -> int:
        with self.SessionTesting() as db:
            return db.scalar(
                select(RestaurantTable.id).where(
                    RestaurantTable.restaurant_id == restaurant_id
                )
            )

    def _available_dish_id(
        self,
        restaurant_id: int = 1,
    ) -> int:
        with self.SessionTesting() as db:
            return db.scalar(
                select(Dish.id).where(
                    Dish.restaurant_id == restaurant_id,
                    Dish.name.like("Available%"),
                )
            )

    def _issue_customer_session(
        self,
        restaurant_id: int = 1,
        *,
        rotate: bool = False,
    ) -> str:
        owner_id = 1 if restaurant_id == 1 else 6
        with self.client_as(
            owner_id,
            active_restaurant_id=restaurant_id,
        ) as owner:
            issued = owner.post(
                (
                    f"/api/dining/{restaurant_id}/tables/"
                    f"{self._table_id(restaurant_id)}/customer-qr"
                ),
                json={"rotate": rotate},
            )
        self.assertEqual(issued.status_code, 200, issued.text)
        qr_path = urlparse(issued.json()["target_url"]).path
        with TestClient(app) as customer:
            entry = customer.get(
                qr_path,
                follow_redirects=False,
            )
        self.assertEqual(entry.status_code, 303, entry.text)
        return entry.headers["location"].rsplit("/", 1)[-1]

    def _create_draft_with_line(
        self,
        token: str,
        *,
        restaurant_id: int = 1,
    ) -> dict:
        suffix = datetime.utcnow().strftime("%H%M%S%f")
        with TestClient(app) as customer:
            created = customer.post(
                f"/api/customer/sessions/{token}/orders",
                json={"idempotency_key": f"order-{suffix}"},
            )
            added = customer.post(
                f"/api/customer/sessions/{token}/order/lines",
                json={
                    "dish_id": self._available_dish_id(
                        restaurant_id
                    ),
                    "quantity": 1,
                    "note": "No onion",
                    "idempotency_key": f"line-{suffix}",
                },
            )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(added.status_code, 200, added.text)
        return added.json()

    def _submit_customer_order(self, token: str) -> dict:
        with TestClient(app) as customer:
            submitted = customer.post(
                (
                    f"/api/customer/sessions/{token}/"
                    "order/submit"
                )
            )
        self.assertEqual(
            submitted.status_code,
            200,
            submitted.text,
        )
        return submitted.json()

    def _customer_order_id(self, token: str) -> int:
        with self.SessionTesting() as db:
            customer_session_id = db.scalar(
                select(CustomerSession.id).where(
                    CustomerSession.session_token == token
                )
            )
            return db.scalar(
                select(Order.id)
                .where(
                    Order.customer_session_id
                    == customer_session_id
                )
                .order_by(Order.id.desc())
            )

    def test_qr_is_random_idempotent_rotatable_and_role_protected(self):
        table_id = self._table_id()
        with self.client_as(1) as owner:
            first = owner.post(
                f"/api/dining/1/tables/{table_id}/customer-qr",
                json={"rotate": False},
            )
            replay = owner.post(
                f"/api/dining/1/tables/{table_id}/customer-qr",
                json={"rotate": False},
            )
        with self.client_as(3) as waiter:
            readable = waiter.get(
                f"/api/dining/1/tables/{table_id}/customer-qr"
            )
            qr_image = waiter.get(
                f"/api/dining/1/tables/{table_id}/customer-qr.png"
            )
            forbidden = waiter.post(
                f"/api/dining/1/tables/{table_id}/customer-qr",
                json={"rotate": True},
            )
        for role_id in (4, 5):
            with self.subTest(role_id=role_id):
                with self.client_as(role_id) as client:
                    sensitive_qr = client.get(
                        (
                            f"/api/dining/1/tables/{table_id}/"
                            "customer-qr"
                        )
                    )
                self.assertEqual(sensitive_qr.status_code, 403)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(
            first.json()["target_url"],
            replay.json()["target_url"],
        )
        token = first.json()["target_url"].rsplit("/", 1)[-1]
        self.assertGreaterEqual(len(token), 40)
        self.assertFalse(token.isdigit())
        self.assertEqual(readable.status_code, 200)
        self.assertEqual(qr_image.status_code, 200)
        self.assertEqual(
            qr_image.headers["content-type"],
            "image/png",
        )
        self.assertTrue(qr_image.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(forbidden.status_code, 403)

        old_path = urlparse(first.json()["target_url"]).path
        with self.client_as(1) as owner:
            rotated = owner.post(
                f"/api/dining/1/tables/{table_id}/customer-qr",
                json={"rotate": True},
            )
        self.assertNotEqual(
            first.json()["target_url"],
            rotated.json()["target_url"],
        )
        with TestClient(app) as customer:
            old_qr = customer.get(old_path)
        self.assertEqual(old_qr.status_code, 404)

    def test_qr_requires_active_service_and_tenant_access(self):
        table_id = self._table_id()
        with self.client_as(1) as owner:
            issued = owner.post(
                f"/api/dining/1/tables/{table_id}/customer-qr",
                json={"rotate": False},
            )
            wrong_tenant = owner.get(
                (
                    f"/api/dining/2/tables/"
                    f"{self._table_id(2)}/customer-qr"
                )
            )
        with self.SessionTesting() as db:
            service_session = db.scalar(
                select(ServiceSession).where(
                    ServiceSession.restaurant_id == 1
                )
            )
            service_session.status = "cancelled"
            service_session.closed_at = datetime.utcnow()
            service_session.closed_by_user_id = 1
            db.commit()
        with TestClient(app) as customer:
            closed = customer.get(
                urlparse(issued.json()["target_url"]).path
            )
        self.assertEqual(wrong_tenant.status_code, 403)
        self.assertEqual(closed.status_code, 409)
        self.assertEqual(
            closed.json()["error"]["code"],
            "customer_table_not_in_service",
        )

    def test_customer_menu_hides_tenant_ids_and_exposes_availability(self):
        token = self._issue_customer_session()
        with TestClient(app) as customer:
            state = customer.get(
                f"/api/customer/sessions/{token}"
            )
            page = customer.get(f"/menu/session/{token}")

        self.assertEqual(state.status_code, 200, state.text)
        payload = state.json()
        self.assertNotIn("restaurant_id", state.text)
        self.assertNotIn("service_session_id", state.text)
        self.assertNotIn("membership", state.text)
        self.assertEqual(payload["table_code"], "C-1")
        self.assertEqual(payload["restaurant"]["currency"], "EUR")
        available = next(
            dish
            for dish in payload["dishes"]
            if dish["name"].startswith("Available")
        )
        unavailable = next(
            dish
            for dish in payload["dishes"]
            if dish["name"].startswith("Unavailable")
        )
        self.assertEqual(available["price"], "10.50")
        self.assertEqual(available["allergens"], "Gluten")
        self.assertTrue(available["is_available"])
        self.assertFalse(unavailable["is_available"])
        self.assertEqual(page.status_code, 200)
        self.assertIn("Enviar al camarero", page.text)
        self.assertNotIn("/admin", page.text)

    def test_customer_draft_crud_snapshots_and_has_no_side_effects(self):
        token = self._issue_customer_session()
        state = self._create_draft_with_line(token)
        line = state["orders"][0]["lines"][0]
        with TestClient(app) as customer:
            updated = customer.patch(
                (
                    f"/api/customer/sessions/{token}/order/"
                    f"lines/{line['id']}"
                ),
                json={"quantity": 2, "note": "No salt"},
            )
        self.assertEqual(updated.status_code, 200, updated.text)
        updated_order = updated.json()["orders"][0]
        self.assertEqual(updated_order["status"], "draft_customer")
        self.assertEqual(updated_order["total_amount"], "21.00")
        self.assertEqual(
            updated_order["lines"][0]["unit_price"],
            "10.50",
        )

        with self.SessionTesting() as db:
            order = db.scalar(select(Order))
            self.assertIsNone(order.created_by_user_id)
            self.assertIsNotNone(order.customer_session_id)
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(KitchenTicket)
                ),
                0,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(
                        InventoryMovement
                    )
                ),
                0,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(AnalyticsEvent)
                ),
                0,
            )

        with TestClient(app) as customer:
            removed = customer.delete(
                (
                    f"/api/customer/sessions/{token}/order/"
                    f"lines/{line['id']}"
                )
            )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(
            removed.json()["orders"][0]["lines"],
            [],
        )

    def test_customer_submit_waiter_approval_is_atomic_and_idempotent(self):
        token = self._issue_customer_session()
        self._create_draft_with_line(token)
        submitted = self._submit_customer_order(token)
        self.assertEqual(
            submitted["orders"][0]["status"],
            "submitted_customer",
        )
        order_id = self._customer_order_id(token)
        with self.SessionTesting() as db:
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(KitchenTicket)
                ),
                0,
            )
        with self.client_as(3) as waiter:
            accepted = waiter.post(
                f"/api/orders/1/{order_id}/customer-approval"
            )
            replay = waiter.post(
                f"/api/orders/1/{order_id}/customer-approval"
            )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["status"], "submitted")
        self.assertTrue(accepted.json()["is_customer_order"])
        self.assertEqual(replay.status_code, 200, replay.text)
        with self.SessionTesting() as db:
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(KitchenTicket)
                ),
                1,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(
                        KitchenTicketLine
                    )
                ),
                1,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(
                        InventoryMovement
                    )
                ),
                0,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(AnalyticsEvent)
                ),
                0,
            )

    def test_customer_rejection_is_auditable_and_idempotent(self):
        token = self._issue_customer_session()
        self._create_draft_with_line(token)
        self._submit_customer_order(token)
        order_id = self._customer_order_id(token)
        with self.client_as(3) as waiter:
            rejected = waiter.post(
                f"/api/orders/1/{order_id}/customer-rejection",
                json={"reason": "Plato agotado"},
            )
            replay = waiter.post(
                f"/api/orders/1/{order_id}/customer-rejection",
                json={"reason": "Otro"},
            )
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "cancelled")
        self.assertEqual(
            rejected.json()["rejection_reason"],
            "Plato agotado",
        )
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(
            replay.json()["rejection_reason"],
            "Plato agotado",
        )
        with self.SessionTesting() as db:
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(KitchenTicket)
                ),
                0,
            )

    def test_customer_cannot_bypass_waiter_and_staff_permissions_apply(self):
        token = self._issue_customer_session()
        self._create_draft_with_line(token)
        order_id = self._customer_order_id(token)
        with TestClient(app) as anonymous:
            internal_submit = anonymous.post(
                f"/api/orders/1/{order_id}/submit"
            )
        with self.client_as(3) as waiter:
            bypass = waiter.post(
                f"/api/orders/1/{order_id}/submit"
            )
        self._submit_customer_order(token)
        with self.client_as(4) as cook:
            cook_rejected = cook.post(
                f"/api/orders/1/{order_id}/customer-approval"
            )
        with self.client_as(5) as viewer:
            viewer_rejected = viewer.post(
                f"/api/orders/1/{order_id}/customer-approval"
            )

        self.assertEqual(internal_submit.status_code, 401)
        self.assertEqual(bypass.status_code, 409)
        self.assertEqual(cook_rejected.status_code, 403)
        self.assertEqual(viewer_rejected.status_code, 403)
        with self.SessionTesting() as db:
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(KitchenTicket)
                ),
                0,
            )

    def test_owner_manager_and_waiter_can_review(self):
        for reviewer_id in (1, 2, 3):
            with self.subTest(reviewer_id=reviewer_id):
                token = self._issue_customer_session()
                self._create_draft_with_line(token)
                self._submit_customer_order(token)
                order_id = self._customer_order_id(token)
                with self.client_as(reviewer_id) as reviewer:
                    accepted = reviewer.post(
                        (
                            f"/api/orders/1/{order_id}/"
                            "customer-approval"
                        )
                    )
                self.assertEqual(
                    accepted.status_code,
                    200,
                    accepted.text,
                )

    def test_expired_revoked_and_cross_session_tokens_are_rejected(self):
        first_token = self._issue_customer_session()
        self._create_draft_with_line(first_token)
        first_line_id = self._state(first_token)["orders"][0][
            "lines"
        ][0]["id"]
        second_token = self._issue_customer_session(2)
        with TestClient(app) as customer:
            own_draft = customer.post(
                f"/api/customer/sessions/{second_token}/orders",
                json={"notes": "Mesa dos"},
            )
            invalid = customer.get(
                "/api/customer/sessions/not-a-token"
            )
            cross_session = customer.patch(
                (
                    f"/api/customer/sessions/{second_token}/order/"
                    f"lines/{first_line_id}"
                ),
                json={"quantity": 2},
            )
        self.assertEqual(own_draft.status_code, 201)
        self.assertEqual(invalid.status_code, 404)
        self.assertEqual(cross_session.status_code, 404)
        self.assertNotIn(
            second_token,
            cross_session.text,
        )
        self.assertEqual(
            cross_session.json()["error"]["path"],
            "/api/customer/sessions/[token]/order/"
            f"lines/{first_line_id}",
        )

        with self.SessionTesting() as db:
            first = db.scalar(
                select(CustomerSession).where(
                    CustomerSession.session_token == first_token
                )
            )
            first.created_at = datetime.utcnow() - timedelta(hours=5)
            first.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
        with TestClient(app) as customer:
            expired = customer.get(
                f"/api/customer/sessions/{first_token}"
            )
        self.assertEqual(expired.status_code, 410)

        active_token = self._issue_customer_session()
        with self.client_as(1) as owner:
            owner.post(
                (
                    f"/api/dining/1/tables/{self._table_id()}/"
                    "customer-qr"
                ),
                json={"rotate": True},
            )
        with TestClient(app) as customer:
            revoked = customer.get(
                f"/api/customer/sessions/{active_token}"
            )
        self.assertEqual(revoked.status_code, 404)

    def test_stock_change_blocks_approval_without_partial_effects(self):
        token = self._issue_customer_session()
        self._create_draft_with_line(token)
        self._submit_customer_order(token)
        order_id = self._customer_order_id(token)
        with self.SessionTesting() as db:
            item = db.scalar(
                select(InventoryItem).where(
                    InventoryItem.restaurant_id == 1
                )
            )
            item.current_stock = 0
            db.commit()
        with self.client_as(3) as waiter:
            rejected = waiter.post(
                f"/api/orders/1/{order_id}/customer-approval"
            )
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(
            rejected.json()["error"]["code"],
            "customer_dish_unavailable",
        )
        with self.SessionTesting() as db:
            order = db.get(Order, order_id)
            self.assertEqual(
                order.status,
                "submitted_customer",
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(KitchenTicket)
                ),
                0,
            )

    def test_customer_pending_order_blocks_close_and_settlement(self):
        token = self._issue_customer_session()
        self._create_draft_with_line(token)
        with self.SessionTesting() as db:
            service_session_id = db.scalar(
                select(CustomerSession.service_session_id).where(
                    CustomerSession.session_token == token
                )
            )
        with self.client_as(3) as waiter:
            close = waiter.post(
                (
                    f"/api/dining/1/sessions/"
                    f"{service_session_id}/close"
                )
            )
            settlement = waiter.post(
                (
                    f"/api/dining/1/sessions/"
                    f"{service_session_id}/settle"
                )
            )
        self.assertEqual(close.status_code, 409)
        self.assertEqual(
            close.json()["error"]["code"],
            "service_session_has_active_orders",
        )
        self.assertEqual(settlement.status_code, 409)
        self.assertEqual(
            settlement.json()["error"]["code"],
            "settlement_orders_pending",
        )

    def test_double_requests_do_not_duplicate_order_or_line(self):
        token = self._issue_customer_session()
        with TestClient(app) as customer:
            for _ in range(2):
                created = customer.post(
                    f"/api/customer/sessions/{token}/orders",
                    json={"idempotency_key": "same-order"},
                )
                self.assertEqual(created.status_code, 201)
            for _ in range(2):
                added = customer.post(
                    (
                        f"/api/customer/sessions/{token}/"
                        "order/lines"
                    ),
                    json={
                        "dish_id": self._available_dish_id(),
                        "quantity": 1,
                        "idempotency_key": "same-line",
                    },
                )
                self.assertEqual(added.status_code, 200)
            customer.post(
                (
                    f"/api/customer/sessions/{token}/"
                    "order/submit"
                )
            )
            replay = customer.post(
                (
                    f"/api/customer/sessions/{token}/"
                    "order/submit"
                )
            )
        self.assertEqual(replay.status_code, 200)
        with self.SessionTesting() as db:
            self.assertEqual(
                db.scalar(select(func.count()).select_from(Order)),
                1,
            )
            self.assertEqual(
                db.scalar(
                    select(func.count()).select_from(OrderLine)
                ),
                1,
            )

    def test_customer_frontend_is_mobile_and_preserves_notes(self):
        project_root = Path(__file__).resolve().parents[1]
        script = (
            project_root / "app/static/js/customer.js"
        ).read_text(encoding="utf-8")
        stylesheet = (
            project_root / "app/static/css/customer.css"
        ).read_text(encoding="utf-8")
        add_handler = script.split(
            'dishesElement.addEventListener("click"',
            maxsplit=1,
        )[1].split(
            'linesElement.addEventListener("click"',
            maxsplit=1,
        )[0]

        self.assertLess(
            add_handler.index("const note ="),
            add_handler.index("withBusy(async"),
        )
        self.assertIn('credentials: "omit"', script)
        self.assertIn("state.busy", script)
        self.assertIn("min-height: 48px", stylesheet)
        self.assertIn("@media (orientation: landscape)", stylesheet)

    def _state(self, token: str) -> dict:
        with TestClient(app) as customer:
            response = customer.get(
                f"/api/customer/sessions/{token}"
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.dependencies.access import get_active_restaurant_id
from app.dependencies.auth import get_current_user
from app.main import app
from app.models import (
    Category,
    Dish,
    KitchenTicket,
    KitchenTicketLine,
    Order,
    OrderLine,
    Restaurant,
    RestaurantMembership,
    RestaurantTable,
    ServiceSession,
    User,
    Zone,
)
from app.services.kitchen_workflow_service import get_kitchen_workspace


class KitchenWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.engine = create_engine(
            f"sqlite:///{cls.temp_dir.name}/kitchen-workflow.db",
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
            db.add_all(
                [
                    Restaurant(id=1, name="Centro", slug="kds-centro"),
                    Restaurant(id=2, name="Playa", slug="kds-playa"),
                ]
            )
            roles = ("owner", "manager", "waiter", "cook", "viewer")
            for user_id, role in enumerate(roles, start=1):
                db.add(
                    User(
                        id=user_id,
                        email=f"kds-{user_id}@hostai.test",
                        hashed_password="not-used",
                        full_name=f"KDS {role.title()}",
                        role=role,
                        restaurant_id=1,
                        is_active=True,
                        created_at=datetime.utcnow(),
                    )
                )
                db.add(
                    RestaurantMembership(
                        user_id=user_id,
                        restaurant_id=1,
                        role=role,
                        is_active=True,
                        created_by_user_id=1,
                    )
                )
            db.add(
                RestaurantMembership(
                    user_id=1,
                    restaurant_id=2,
                    role="owner",
                    is_active=True,
                    created_by_user_id=1,
                )
            )
            db.commit()

    def setUp(self):
        with self.SessionTesting() as db:
            db.execute(delete(KitchenTicketLine))
            db.execute(delete(KitchenTicket))
            db.execute(delete(OrderLine))
            db.execute(delete(Order))
            db.execute(delete(ServiceSession))
            db.execute(delete(RestaurantTable))
            db.execute(delete(Zone))
            db.execute(delete(Dish))
            db.execute(delete(Category))
            for restaurant_id, label in ((1, "Centro"), (2, "Playa")):
                category = Category(
                    restaurant_id=restaurant_id,
                    name=f"Menu {label}",
                )
                zone = Zone(
                    restaurant_id=restaurant_id,
                    name=f"Zone {label}",
                )
                db.add_all([category, zone])
                db.flush()
                dish = Dish(
                    restaurant_id=restaurant_id,
                    category_id=category.id,
                    name=f"Rice {label}",
                    price=15,
                    allergens="Apio",
                )
                table = RestaurantTable(
                    restaurant_id=restaurant_id,
                    zone_id=zone.id,
                    code=f"M{restaurant_id}",
                    capacity=4,
                )
                db.add_all([dish, table])
                db.flush()
                service_session = ServiceSession(
                    restaurant_id=restaurant_id,
                    table_id=table.id,
                    status="open",
                    opened_at=datetime.utcnow(),
                    guest_count=2,
                    opened_by_user_id=1,
                )
                db.add(service_session)
                db.flush()
                self._add_ticket_graph(
                    db,
                    restaurant_id=restaurant_id,
                    service_session=service_session,
                    table=table,
                    dish=dish,
                    note=f"Allergy {label}",
                )
            db.commit()

    def _add_ticket_graph(
        self,
        db,
        *,
        restaurant_id: int,
        service_session: ServiceSession,
        table: RestaurantTable,
        dish: Dish,
        note: str,
    ) -> KitchenTicket:
        now = datetime.utcnow()
        order = Order(
            restaurant_id=restaurant_id,
            service_session_id=service_session.id,
            status="submitted",
            created_by_user_id=1,
            submitted_at=now,
        )
        db.add(order)
        db.flush()
        order_line = OrderLine(
            restaurant_id=restaurant_id,
            order_id=order.id,
            dish_id=dish.id,
            dish_name=dish.name,
            quantity=2,
            unit_price=dish.price,
            note=note,
        )
        db.add(order_line)
        db.flush()
        ticket = KitchenTicket(
            restaurant_id=restaurant_id,
            order_id=order.id,
            service_session_id=service_session.id,
            table_id=table.id,
            status="pending",
            created_by_user_id=1,
            created_at=now,
            updated_at=now,
        )
        db.add(ticket)
        db.flush()
        db.add(
            KitchenTicketLine(
                restaurant_id=restaurant_id,
                kitchen_ticket_id=ticket.id,
                order_line_id=order_line.id,
                dish_id=dish.id,
                dish_name=dish.name,
                quantity=2,
                note=note,
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )
        return ticket

    @contextmanager
    def client_as(self, user_id: int, *, active_restaurant_id: int = 1):
        roles = {
            1: "owner",
            2: "manager",
            3: "waiter",
            4: "cook",
            5: "viewer",
        }
        user = User(
            id=user_id,
            email=f"kds-{user_id}@hostai.test",
            hashed_password="not-used",
            full_name=f"KDS {roles[user_id].title()}",
            role=roles[user_id],
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

    def test_owner_manager_and_cook_can_open_kitchen_workspace(self):
        for user_id in (1, 2, 4):
            with self.subTest(user_id=user_id), self.client_as(user_id) as client:
                response = client.get("/staff/kitchen")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn("Producción en curso", response.text)

    def test_waiter_and_viewer_cannot_open_operational_kitchen(self):
        for user_id in (3, 5):
            with self.subTest(user_id=user_id), self.client_as(user_id) as client:
                response = client.get("/staff/kitchen")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["error"]["code"], "permission_denied")

    def test_legacy_kitchen_entry_redirects_to_workspace(self):
        with self.client_as(4) as cook:
            response = cook.get("/app/kitchen", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/staff/kitchen")

    def test_ticket_card_contains_table_zone_lines_notes_and_allergens(self):
        with self.client_as(4) as cook:
            response = cook.get("/staff/kitchen")

        self.assertIn("Mesa M1", response.text)
        self.assertIn("Zone Centro", response.text)
        self.assertIn("2× Rice Centro", response.text)
        self.assertIn("Allergy Centro", response.text)
        self.assertIn("Alérgenos: Apio", response.text)

    def test_status_filters_return_only_requested_tickets(self):
        with self.SessionTesting() as db:
            ticket = db.scalar(
                select(KitchenTicket).where(KitchenTicket.restaurant_id == 1)
            )
            ticket.status = "preparing"
            ticket.started_at = datetime.utcnow()
            ticket.lines[0].status = "preparing"
            ticket.lines[0].started_at = datetime.utcnow()
            db.commit()

        with self.client_as(4) as cook:
            pending = cook.get("/api/kitchen/1/tickets?status=pending")
            preparing = cook.get("/api/kitchen/1/tickets?status=preparing")
            ready = cook.get("/api/kitchen/1/tickets?status=ready")

        self.assertEqual(pending.json(), [])
        self.assertEqual(len(preparing.json()), 1)
        self.assertEqual(ready.json(), [])

    def test_active_restaurant_switch_isolates_kitchen_cards(self):
        with self.client_as(1, active_restaurant_id=2) as owner:
            response = owner.get("/staff/kitchen")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Playa", response.text)
        self.assertIn("Mesa M2", response.text)
        self.assertIn("Rice Playa", response.text)
        self.assertNotIn("Rice Centro", response.text)

    def test_revoked_membership_is_revalidated(self):
        with self.SessionTesting() as db:
            membership = db.scalar(
                select(RestaurantMembership).where(
                    RestaurantMembership.user_id == 4,
                    RestaurantMembership.restaurant_id == 1,
                )
            )
            membership.is_active = False
            db.commit()

        try:
            with self.client_as(4) as cook:
                response = cook.get("/staff/kitchen")
            self.assertEqual(response.status_code, 403)
        finally:
            with self.SessionTesting() as db:
                membership = db.scalar(
                    select(RestaurantMembership).where(
                        RestaurantMembership.user_id == 4,
                        RestaurantMembership.restaurant_id == 1,
                    )
                )
                membership.is_active = True
                db.commit()

    def test_waiter_order_payload_tracks_kitchen_status(self):
        with self.SessionTesting() as db:
            order_id = db.scalar(
                select(Order.id).where(Order.restaurant_id == 1)
            )
            ticket_id = db.scalar(
                select(KitchenTicket.id).where(KitchenTicket.restaurant_id == 1)
            )

        with self.client_as(3) as waiter:
            pending = waiter.get(f"/api/orders/1/{order_id}")
        with self.client_as(4) as cook:
            cook.post(f"/api/kitchen/1/tickets/{ticket_id}/start")
        with self.client_as(3) as waiter:
            preparing = waiter.get(f"/api/orders/1/{order_id}")

        self.assertEqual(pending.json()["kitchen_status"], "pending")
        self.assertEqual(preparing.json()["kitchen_status"], "preparing")

    def test_workspace_query_count_does_not_grow_with_ticket_count(self):
        with self.SessionTesting() as db:
            service_session = db.scalar(
                select(ServiceSession).where(ServiceSession.restaurant_id == 1)
            )
            table = db.scalar(
                select(RestaurantTable).where(RestaurantTable.restaurant_id == 1)
            )
            dish = db.scalar(select(Dish).where(Dish.restaurant_id == 1))
            for index in range(3):
                self._add_ticket_graph(
                    db,
                    restaurant_id=1,
                    service_session=service_session,
                    table=table,
                    dish=dish,
                    note=f"Extra {index}",
                )
            db.commit()
            actor = db.get(User, 4)
            statements = []

            def count_statement(*_args):
                statements.append(1)

            event.listen(self.engine, "before_cursor_execute", count_statement)
            try:
                context = get_kitchen_workspace(db, actor, 1)
            finally:
                event.remove(self.engine, "before_cursor_execute", count_statement)

        self.assertEqual(len(context["tickets"]), 4)
        self.assertLessEqual(len(statements), 10)

    def test_workspace_is_responsive_touch_first_and_polling_is_visibility_aware(self):
        with self.client_as(4) as cook:
            response = cook.get("/staff/kitchen")

        project_root = Path(__file__).resolve().parents[1]
        script = (project_root / "app/static/js/kitchen.js").read_text(
            encoding="utf-8"
        )
        stylesheet = (project_root / "app/static/css/kitchen.css").read_text(
            encoding="utf-8"
        )

        self.assertIn('name="viewport"', response.text)
        self.assertIn('class="kitchen-grid"', response.text)
        self.assertIn("kitchen.css", response.text)
        self.assertIn("kitchen.js", response.text)
        self.assertNotIn("<table", response.text)
        self.assertIn("min-height: 52px", stylesheet)
        self.assertIn("orientation: landscape", stylesheet)
        self.assertIn("@media (max-width: 700px)", stylesheet)
        self.assertIn("document.hidden", script)
        self.assertIn("pollIntervalMs", script)
        self.assertIn("button.disabled = true", script)
        self.assertIn("window.confirm", script)
        self.assertNotIn("OperationalTransaction", script)
